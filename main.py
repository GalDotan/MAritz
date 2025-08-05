import sys
import time
import csv
import tempfile
import math
import bisect
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QFileDialog,
    QLabel, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene,
    QSystemTrayIcon, QMenu
)
from PySide6.QtCore import (
    QObject, QThread, Signal, QTimer, Qt
)
from PySide6.QtGui import (
    QPalette, QColor, QPen, QBrush, QPainter, QFont, QIcon, QAction
)

import struct
from typing import SupportsBytes

# --- NetworkTables import ---
try:
    from ntcore import NetworkTableInstance
except ImportError:
    NetworkTableInstance = None

# --- WPILOG parser (unchanged) ---
floatStruct = struct.Struct("<f")
doubleStruct = struct.Struct("<d")
kControlStart, kControlFinish, kControlSetMetadata = 0, 1, 2

class StartRecordData:
    __slots__ = ("entry","name","type","metadata")
    def __init__(self, entry, name, type, metadata):
        self.entry, self.name, self.type, self.metadata = entry, name, type, metadata

class DataLogRecord:
    __slots__ = ("entry","timestamp","data")
    def __init__(self, entry:int, timestamp:int, data:SupportsBytes):
        self.entry, self.timestamp, self.data = entry, timestamp, data
    def isControl(self): return self.entry==0
    def isStart(self):    return self.isControl() and len(self.data)>=17 and self.data[0]==kControlStart
    def isFinish(self):   return self.isControl() and len(self.data)==5 and self.data[0]==kControlFinish
    def isSetMetadata(self): return self.isControl() and len(self.data)>=9 and self.data[0]==kControlSetMetadata
    def getStartData(self):
        d=self.data
        entry=int.from_bytes(d[1:5],"little")
        name,pos=self._readInnerString(5)
        typ,pos =self._readInnerString(pos)
        meta,_  =self._readInnerString(pos)
        return StartRecordData(entry,name,typ,meta)
    def getFinishEntry(self):
        return int.from_bytes(self.data[1:5],"little")
    def getMetadataData(self):
        buf=self.data
        eid=int.from_bytes(buf[1:5],"little")
        ln =int.from_bytes(buf[5:9],"little")
        meta=buf[9:9+ln].decode("utf-8")
        return eid, meta
    def _readInnerString(self,pos):
        ln=int.from_bytes(self.data[pos:pos+4],"little")
        end=pos+4+ln
        return self.data[pos+4:end].decode("utf-8"), end
    def getBoolean(self): return bool(self.data[0])
    def getInteger(self): return int.from_bytes(self.data,"little",signed=True)
    def getFloat(self):   return floatStruct.unpack(self.data)[0]
    def getDouble(self):  return doubleStruct.unpack(self.data)[0]
    def getString(self):  return self.data.decode("utf-8")
    def getRaw(self):     return self.data.hex()
    def getBooleanArray(self): return ",".join(str(bool(b)) for b in self.data)
    def getIntegerArray(self):
        cnt=len(self.data)//8
        vals=[int.from_bytes(self.data[i*8:(i+1)*8],"little",signed=True) for i in range(cnt)]
        return ",".join(map(str,vals))
    def getFloatArray(self):
        cnt=len(self.data)//4
        vals=struct.unpack("<"+"f"*cnt,self.data)
        return ",".join(f"{v:.6g}" for v in vals)
    def getDoubleArray(self):
        cnt=len(self.data)//8
        vals=struct.unpack("<"+"d"*cnt,self.data)
        return ",".join(f"{v:.6g}" for v in vals)
    def getStringArray(self):
        size=int.from_bytes(self.data[0:4],"little")
        arr=[]; pos=4
        for _ in range(size):
            ln=int.from_bytes(self.data[pos:pos+4],"little"); pos+=4
            s=self.data[pos:pos+ln].decode("utf-8"); pos+=ln
            arr.append(s)
        return ",".join(arr)

class DataLogIterator:
    __slots__ = ("buf","pos")
    def __init__(self, buf, pos): self.buf, self.pos = buf, pos
    def __iter__(self): return self
    def __next__(self):
        if self.pos+4>len(self.buf): raise StopIteration
        head=self.buf[self.pos]
        eL=(head&0x3)+1; sL=((head>>2)&0x3)+1; tL=((head>>4)&0x7)+1
        hdr=1+eL+sL+tL
        if self.pos+hdr>len(self.buf): raise StopIteration
        entry=sum(self.buf[self.pos+1+i]<<(8*i) for i in range(eL))
        size =sum(self.buf[self.pos+1+eL+i]<<(8*i) for i in range(sL))
        ts   =sum(self.buf[self.pos+1+eL+sL+i]<<(8*i) for i in range(tL))
        data =self.buf[self.pos+hdr:self.pos+hdr+size]
        self.pos+=hdr+size
        return DataLogRecord(entry,ts,data)

class DataLogReader:
    __slots__ = ("buf",)
    def __init__(self, buf): self.buf=buf
    def __iter__(self):
        hdr_sz=int.from_bytes(self.buf[8:12],"little")
        return DataLogIterator(self.buf,12+hdr_sz)

class ConvertWorker(QObject):
    finished=Signal(str)
    def __init__(self, filepath:Path):
        super().__init__(); self.filepath=filepath
    def run(self):
        buf=self.filepath.read_bytes()
        reader=DataLogReader(buf)
        entries,rows={},[]
        for rec in reader:
            if rec.isStart():
                sd=rec.getStartData(); entries[sd.entry]=sd
            elif rec.isFinish():
                entries.pop(rec.getFinishEntry(),None)
            elif rec.isSetMetadata():
                eid,meta=rec.getMetadataData()
                if eid in entries: entries[eid].metadata=meta
            elif rec.isControl():
                continue
            else:
                sd=entries.get(rec.entry)
                if not sd: continue
                ts=rec.timestamp/1e6; tp=sd.type
                try:
                    if   tp=="boolean":     val=rec.getBoolean()
                    elif tp=="int64":       val=rec.getInteger()
                    elif tp=="float":       val=rec.getFloat()
                    elif tp=="double":      val=rec.getDouble()
                    elif tp=="string":      val=rec.getString()
                    elif tp=="boolean[]":   val=rec.getBooleanArray()
                    elif tp=="int64[]":     val=rec.getIntegerArray()
                    elif tp=="float[]":     val=rec.getFloatArray()
                    elif tp=="double[]":    val=rec.getDoubleArray()
                    elif tp=="string[]":    val=rec.getStringArray()
                    else:                   val=rec.getRaw()
                except:
                    val=""
                rows.append((f"{ts:.6f}",sd.name,tp,str(val)))
        tmp=tempfile.NamedTemporaryFile(delete=False,suffix=".csv",
                                        mode="w",newline="",encoding="utf-8")
        w=csv.writer(tmp); w.writerow(("timestamp","key","type","value")); w.writerows(rows)
        path=tmp.name; tmp.close()
        self.finished.emit(path)

# --- TimelineView (unchanged) ---
class TimelineView(QGraphicsView):
    positionClicked = Signal(float)
    def __init__(self, duration, parent=None):
        super().__init__(parent)
        self.duration=duration; self.segments=[]; self.cursor_x=0.0
        self.setScene( QGraphicsScene(self) )
        self.setRenderHints(self.renderHints()|QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self._draw_segments()
    def set_segments(self, segments):
        self.segments=segments; self._draw_segments()
    def _draw_segments(self):
        sc=self.scene(); sc.clear()
        w=max(800,int(self.duration*100))
        sc.setSceneRect(0,0,w,80)
        for s,e,st in self.segments:
            if s>1000: continue
            ex=min(e,1000)
            x0=s*100; width=(ex-s)*100
            color=QColor(200,0,0) if st=="estop" else \
                  QColor(80,80,80) if st=="disabled" else \
                  QColor(0,200,0) if st=="autonomous" else \
                  QColor(0,0,200)
            sc.addRect(x0,0,width,80,QPen(Qt.NoPen),QBrush(color))
        sc.addRect(0,0,w,80,QPen(Qt.white))
    def wheelEvent(self, ev):
        dx=ev.angleDelta().x(); dy=ev.angleDelta().y()
        if dx:
            sb=self.horizontalScrollBar(); sb.setValue(sb.value()-dx)
            return
        factor=1.2**(dy/120) if dy else 1.0
        cur=self.transform().m11()
        sw=self.sceneRect().width(); vw=self.viewport().width()
        min_s=vw/sw if sw>0 else 1.0
        new=cur*factor
        if new<min_s: factor=min_s/cur
        self.scale(factor,1); self.viewport().update()
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            # use the new .position() (QPointF) instead of .pos()
            p = ev.position()
            pt = self.mapToScene(p.x(), p.y())
            ts = max(0, min(pt.x()/100, self.duration, 1000))
            self.positionClicked.emit(ts)
        super().mousePressEvent(ev)
    def update_cursor(self, t):
        if t>1000: return
        self.cursor_x=t*100
        self.ensureVisible(self.cursor_x,0,50,80)
        self.viewport().update()
    def drawForeground(self, painter, rect):
        painter.save(); painter.resetTransform()
        pen=QPen(Qt.white); pen.setWidth(1); painter.setPen(pen)
        font=QFont(); font.setPixelSize(10); painter.setFont(font)
        vw=self.viewport().width(); vh=self.viewport().height()
        left=self.mapToScene(0,0).x()/100; right=self.mapToScene(vw,0).x()/100
        span=right-left; target=span/10
        nice=[1,2,5,10,20,30,60,120,300,600]
        interval=next((n for n in nice if n>=target),nice[-1])
        first=math.floor(left/interval)*interval
        t=first
        while t<=right:
            if 0<=t<=1000:
                x=self.mapFromScene(t*100,0).x()
                painter.drawLine(x,vh-20,x,vh-5)
                painter.drawText(x+2,vh-22,f"{int(t)}s")
            t+=interval
        pen=QPen(Qt.white,2); pen.setCosmetic(True); painter.setPen(pen)
        x=self.mapFromScene(self.cursor_x,0).x()
        painter.drawLine(x,0,x,vh)
        painter.restore()

# --- Controller (unchanged) ---
class Controller(QObject):
    loaded=Signal(int,float)
    segmentsChanged=Signal(list)
    progressChanged=Signal(int,int)
    elapsedChanged=Signal(float)

    def __init__(self):
        super().__init__()
        self.csv_path=None
        self.log=[]; self.timestamps=[]
        self.idx=0; self.start_time=0.0
        self.is_publishing=False
        self.segments=[]
        self.nt_inst=NetworkTableInstance.getDefault() if NetworkTableInstance else None
        self.nt_table=None
        self.timer=QTimer(self); self.timer.setInterval(10); self.timer.timeout.connect(self._tick)

    def open_log(self, parent):
        path,_=QFileDialog.getOpenFileName(parent,"Open WPILog","*.wpilog")
        if not path: return
        self.worker=ConvertWorker(Path(path))
        self.thread=QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_converted)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

    def _on_converted(self, csv_path):
        self.csv_path=csv_path
        self.log=[]
        with open(csv_path,newline="",encoding="utf-8") as f:
            r=csv.reader(f); next(r)
            for row in r:
                try: ts=float(row[0])
                except: continue
                if ts>1000: continue
                self.log.append((ts,row[1],row[2],row[3]))
        self.log.sort(key=lambda x:x[0])
        self.timestamps=[r[0] for r in self.log]
        total=len(self.log); duration=self.timestamps[-1] if total else 1.0

        flags={"enabled":False,"autonomous":False,"estop":False}
        def state():
            if flags["estop"]: return "estop"
            if not flags["enabled"]: return "disabled"
            if flags["autonomous"]: return "autonomous"
            return "teleop"
        segs=[]; cur=state(); st=0.0
        for ts,key,_,val in self.log:
            if key.startswith("DS:"):
                f=key.split("DS:")[1]
                if f in flags:
                    flags[f]=(val=="True")
                    ns=state()
                    if ns!=cur:
                        segs.append((st,ts,cur)); cur=ns; st=ts
        segs.append((st,duration,cur))
        self.segments=segs

        self.loaded.emit(total,duration)
        self.segmentsChanged.emit(segs)

    def toggle_replay(self):
        if not self.log: return
        if not self.timer.isActive():
            base=self.timestamps[self.idx] if self.idx<len(self.timestamps) else 0.0
            self.start_time=time.perf_counter()-base
            if self.is_publishing and self.nt_inst:
                self.nt_inst.startClient4("log-replay"); self.nt_inst.setServer("localhost")
                self.nt_table=self.nt_inst.getTable("log")
            self.timer.start()
        else:
            self.timer.stop()

    def toggle_publish(self):
        self.is_publishing=not self.is_publishing
        if not self.is_publishing and self.nt_inst:
            self.nt_inst.stopClient()

    def seek(self, t):
        self.idx=bisect.bisect_left(self.timestamps,t)
        self.start_time=time.perf_counter()-t

    def _tick(self):
        now=time.perf_counter()-self.start_time
        total=len(self.log)
        while self.idx<total and self.log[self.idx][0]<=now:
            ts,key,tp,val=self.log[self.idx]
            if self.is_publishing and self.nt_table:
                if tp=="boolean":
                    self.nt_table.putBoolean(key,val=="True")
                elif tp in ("int64","float","double"):
                    try: num=float(val)
                    except: num=0.0
                    self.nt_table.putNumber(key,num)
                elif tp=="string":
                    self.nt_table.putString(key,val)
                elif tp=="boolean[]":
                    arr=val.split(",") if val else []
                    bools=[e=="True" for e in arr]
                    self.nt_table.putBooleanArray(key,bools)
                elif tp in ("int64[]","float[]","double[]"):
                    arr=val.split(",") if val else []
                    nums=[]
                    for e in arr:
                        try: nums.append(float(e))
                        except: nums.append(0.0)
                    self.nt_table.putNumberArray(key,nums)
                elif tp=="string[]":
                    arr=val.split(",") if val else []
                    self.nt_table.putStringArray(key,arr)
            self.idx+=1
        self.progressChanged.emit(self.idx,total)
        self.elapsedChanged.emit(now)

# --- TrayWindow with status + elapsed ---
class TrayWindow(QWidget):
    def __init__(self, ctrl, full_win):
        super().__init__(None, Qt.Tool)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedSize(600,180)

        self.ctrl, self.full = ctrl, full_win

        # Buttons
        btn_open   = QPushButton("Open Log")
        btn_open.clicked.connect(self._on_open)
        self.btn_replay = QPushButton("Play")
        self.btn_replay.setEnabled(False)
        self.btn_replay.clicked.connect(self._on_toggle_replay)
        self.btn_pub    = QPushButton("Start Broadcast")
        self.btn_pub.setEnabled(False)
        self.btn_pub.clicked.connect(self._on_toggle_pub)
        btn_full   = QPushButton("Full App")
        btn_full.clicked.connect(full_win.show)
        btn_close  = QPushButton("✕")
        btn_close.setFixedSize(20,20)
        btn_close.clicked.connect(self.hide)
        btn_close.setStyleSheet("background:transparent; color:white;")

        # Status & elapsed
        self.lbl_status  = QLabel("Log not loaded")
        self.lbl_status.setStyleSheet("color:white")
        self.lbl_elapsed = QLabel("0.00s")
        self.lbl_elapsed.setStyleSheet("color:white")

        # Timeline
        self.timeline = TimelineView(1.0)
        self.timeline.positionClicked.connect(lambda ts: (ctrl.seek(ts), self.timeline.update_cursor(ts)))

        # Layout
        top = QHBoxLayout()
        top.addWidget(btn_open)
        top.addWidget(self.btn_replay)
        top.addWidget(self.btn_pub)
        top.addWidget(btn_full)
        top.addSpacing(15)
        top.addWidget(self.lbl_status)
        top.addSpacing(15)
        top.addWidget(self.lbl_elapsed)
        top.addStretch()
        top.addWidget(btn_close)
        top.setContentsMargins(5,5,5,5)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.timeline)
        layout.setContentsMargins(2,2,2,2)
        self.setLayout(layout)

        # Signal connections
        ctrl.loaded.connect(self._on_loaded)
        ctrl.segmentsChanged.connect(self.timeline.set_segments)
        ctrl.elapsedChanged.connect(self._on_elapsed)
        # Play/stop updates
        ctrl.progressChanged.connect(lambda *_: self._update_play_status())
        ctrl.elapsedChanged.connect(
            lambda e: self.timeline.update_cursor(min(e, self.timeline.duration))
        )

    def _on_open(self):
        self.lbl_status.setText("Loading log")
        self.lbl_status.setStyleSheet("color:orange")
        self.ctrl.open_log(self)

    def _on_loaded(self, total, dur):
        self.btn_replay.setEnabled(True)
        self.btn_pub.setEnabled(True)

        # redraw segments
        self.timeline.duration = dur
        self.timeline.set_segments(self.ctrl.segments)

        # ── ZOOM OUT TO SHOW ENTIRE TIMELINE ──
        # 1) reset any previous zoom/scale
        self.timeline.resetTransform()
        # 2) compute the minimum horizontal scale so scene fits view
        view_w = self.timeline.viewport().width()
        scene_w = self.timeline.sceneRect().width()
        if scene_w > 0:
            min_scale = view_w / scene_w
            self.timeline.scale(min_scale, 1.0)
        # ─────────────────────────────────────────

        # reset cursor & status
        self.timeline.update_cursor(0.0)
        self.lbl_status.setText("Ready")
        self.lbl_status.setStyleSheet("color:white")
        self.lbl_elapsed.setText("0.00s")

        self._update_play_status()
        self._update_pub_status()

    def _on_toggle_replay(self):
        self.ctrl.toggle_replay()
        self._update_play_status()

    def _on_toggle_pub(self):
        self.ctrl.toggle_publish()
        self._update_pub_status()

    def _update_play_status(self):
        running = self.ctrl.timer.isActive()
        self.btn_replay.setText("Stop Replay" if running else "Play")
        if running:
            self.btn_replay.setStyleSheet("background-color: #53c268; color: white;")
        else:
            self.btn_replay.setStyleSheet("background-color: #cf4e4e; color: white;")
         # don't overwrite "Loading log"
        if self.lbl_status.text() not in ("Loading log",):
             status = "Running" if running else "Ready"
             self.lbl_status.setText(status)

    def _update_pub_status(self):
        on = self.ctrl.is_publishing
        # text
        self.btn_pub.setText("Stop Broadcast" if on else "Start Broadcast")
        # color
        if on:
            self.btn_pub.setStyleSheet("background-color: #53c268; color: white;")
        else:
            self.btn_pub.setStyleSheet("background-color: #cf4e4e; color: white;")

    def _on_elapsed(self, e):
        self.lbl_elapsed.setText(f"{e:.2f}s")

    def showEvent(self, event):
        full = QApplication.primaryScreen().geometry()
        avail = QApplication.primaryScreen().availableGeometry()
        tb_height = full.height() - avail.height()
        margin = 10
        x = avail.x() + avail.width() - self.width() - margin
        y = full.height() - tb_height - self.height() - margin
        self.move(x, y)
        super().showEvent(event)

# --- FullWindow (unchanged) ---
class FullWindow(QMainWindow):
    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.setWindowTitle("MAritz")
        self.setGeometry(200,200,900,200)
        p = QPalette()
        p.setColor(QPalette.Window, QColor(53,53,53))
        p.setColor(QPalette.WindowText, Qt.white)
        p.setColor(QPalette.Base, QColor(25,25,25))
        p.setColor(QPalette.Text, Qt.white)
        p.setColor(QPalette.Button, QColor(53,53,53))
        p.setColor(QPalette.ButtonText, Qt.white)
        QApplication.setPalette(p)

        btn_open = QPushButton("Open Log")
        btn_open.clicked.connect(lambda: ctrl.open_log(self))
        self.btn_replay = QPushButton("Play")
        self.btn_replay.setEnabled(False)
        self.btn_replay.clicked.connect(lambda: (ctrl.toggle_replay(), self._update()))
        self.btn_pub = QPushButton("Start Broadcast")
        self.btn_pub.setEnabled(False)
        self.btn_pub.clicked.connect(lambda: (ctrl.toggle_publish(), self._update_pub()))
        btn_back = QPushButton("Back to Tray")
        btn_back.clicked.connect(self.hide)

        self.timeline = TimelineView(1.0)
        self.timeline.positionClicked.connect(lambda ts: (
            ctrl.seek(ts),
            self.timeline.update_cursor(ts),
            self._update_progress(ts)
        ))

        self.lbl_progress = QLabel("0/0")
        self.lbl_elapsed  = QLabel("0.00s")

        top = QHBoxLayout()
        top.addWidget(btn_open)
        top.addWidget(self.btn_replay)
        top.addWidget(self.btn_pub)
        top.addWidget(btn_back)
        top.addWidget(self.lbl_progress)
        top.addWidget(self.lbl_elapsed)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.timeline)

        w = QWidget()
        w.setLayout(layout)
        self.setCentralWidget(w)

        ctrl.loaded.connect(lambda t,d: (
            self.btn_replay.setEnabled(True),
            self.btn_pub.setEnabled(True),
            setattr(self.timeline, 'duration', d),
            self.timeline.set_segments(ctrl.segments),
            self._update_progress(0)
        ))
        ctrl.progressChanged.connect(lambda i, tot: self.lbl_progress.setText(f"{i}/{tot}"))
        ctrl.elapsedChanged.connect(lambda e: self.lbl_elapsed.setText(f"{e:.2f}s"))
        ctrl.elapsedChanged.connect(lambda e: self.timeline.update_cursor(min(e,self.timeline.duration)))

    def _update(self):
        running = self.ctrl.timer.isActive()
        self.btn_replay.setText("Stop Replay" if running else "Play")
        if running:
            self.btn_replay.setStyleSheet("background-color: #53c268; color: white;")
        else:
            self.btn_replay.setStyleSheet("background-color: #cf4e4e; color: white;")

    def _update_pub(self):
        on = self.ctrl.is_publishing
        self.btn_pub.setText("Stop Broadcast" if on else "Start Broadcast")
        if on:
            self.btn_pub.setStyleSheet("background-color: #53c268; color: white;")
        else:
            self.btn_pub.setStyleSheet("background-color: #cf4e4e; color: white;")

    def _update_progress(self, ts):
        idx = bisect.bisect_left(self.ctrl.timestamps, ts)
        tot = len(self.ctrl.log)
        self.lbl_progress.setText(f"{idx}/{tot}")
        self.lbl_elapsed.setText(f"{ts:.2f}s")

def main():
    app = QApplication(sys.argv)

    base = Path(__file__).parent
    icon_path = base/"icon.ico"
    tray_icon = QIcon(str(icon_path))
    app.setWindowIcon(tray_icon)

    ctrl     = Controller()
    full     = FullWindow(ctrl)
    full.setWindowIcon(tray_icon)
    tray_win = TrayWindow(ctrl, full)
    tray_win.setWindowIcon(tray_icon)

    tray = QSystemTrayIcon(tray_icon, app)
    tray.setToolTip("MAritz")
    menu = QMenu()
    show_action = QAction("Show Controls")
    show_action.triggered.connect(tray_win.show)
    exit_action = QAction("Exit")
    exit_action.triggered.connect(app.quit)
    menu.addAction(show_action)
    menu.addAction(exit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: tray_win.show() if r==QSystemTrayIcon.Trigger else None)
    tray.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()