#!/usr/bin/env python3
"""Stellar App Monitor — PySide6 desktop client for AMD BC250 / ESP32-C3."""
import os, sys, re, glob, time, subprocess, threading, urllib.request, collections
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QThread, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath, QLinearGradient, QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QHBoxLayout,QVBoxLayout,QGridLayout,QPushButton,
 QLabel,QPlainTextEdit,QComboBox,QStackedWidget,QFrame,QProgressBar,QMessageBox,QGroupBox)

BASE=Path(__file__).resolve().parent
HOME=Path.home()
UNIT='bc250-display.service'
UNIT_PATH=HOME/'.config/systemd/user'/UNIT
MONITOR_DIR=HOME/'.local/share/bc250-display'
FIRMWARE=BASE/'firmware/stellar_monitor.merged.bin'
ARDUINO=HOME/'.local/bin/arduino-cli'
def command(args,timeout=15):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    return p.returncode,(p.stdout+p.stderr).strip()
def sensor(name):
    for label in Path('/sys/class/hwmon').glob('hwmon*/name'):
        try:
            chip=label.read_text().strip()
            if chip!=name: continue
            for p in sorted(label.parent.glob('temp*_input')):
                try:
                    number=re.search(r'temp(\d+)_input',p.name).group(1)
                    txt=label.parent/f'temp{number}_label'
                    lab=txt.read_text().strip() if txt.exists() else 'temperatura'
                    if name=='k10temp' and lab not in ('Tctl','Tdie'): continue
                    if name=='amdgpu' and 'edge' not in lab.lower() and txt.exists(): continue
                    return round(int(p.read_text())/1000,1),f'{chip} · {lab}'
                except (OSError,ValueError,AttributeError): pass
        except OSError: pass
    return None,name
def ports():
    from serial.tools import list_ports
    return sorted([x for x in list_ports.comports() if x.vid is not None], key=lambda x:x.device)
class Job(QThread):
    line=Signal(str);progress=Signal(int);done=Signal(bool,str)
    def __init__(self,func): super().__init__();self.func=func
    def run(self):
        try:self.func(self);self.done.emit(True,'Concluído')
        except Exception as e:self.done.emit(False,str(e))
    def emit(self,msg):self.line.emit(msg)
    def cmd(self,argv,timeout=90):
        self.emit('$ '+' '.join(map(str,argv)))
        rc,out=command(list(map(str,argv)),timeout)
        if out:self.emit(out[-2500:])
        if rc:raise RuntimeError(f'Comando retornou código {rc}: {out[-400:]}')
class CometBrand(QWidget):
    """Identidade STELLAR: cometa ao fundo do lettering, sem caixa azul."""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(113)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for offset,alpha,width in [(0,75,3),(6,125,2),(11,185,2)]:
            path=QPainterPath(QPointF(20,62+offset))
            path.cubicTo(56,22+offset,105,20+offset,167,15)
            pen=QPen(QColor(23,180,244,alpha),width)
            p.setPen(pen);p.drawPath(path)
        p.setPen(Qt.NoPen);p.setBrush(QColor('#4bdcff'))
        p.drawEllipse(QPointF(168,15),7,7)
        p.setPen(QColor('#f6fbff'));font=QFont('Noto Sans',21,QFont.Bold)
        p.setFont(font);p.drawText(QRectF(26,40,180,46),Qt.AlignCenter,'STELLAR')
        p.setPen(QColor('#9bbde1'));p.setFont(QFont('Noto Sans',11))
        p.drawText(QRectF(26,77,180,26),Qt.AlignCenter,'App Monitor')
        p.end()


class TemperatureCard(QWidget):
    """Gráfico translúcido renderizado atrás do valor, sem dependências gráficas extras."""
    def __init__(self,label,tint):
        super().__init__()
        self.label=label
        self.tint=QColor(tint)
        self.samples=collections.deque(maxlen=50)
        self.value=None
        self.setMinimumHeight(188)

    def update_reading(self,value,label):
        self.value=value
        self.label=label
        self.samples.append(value)
        self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(self.rect()).adjusted(1,1,-1,-1)
        p.setPen(QPen(self.tint,1))
        p.setBrush(QColor('#112a42' if self.tint.blue()>self.tint.green() else '#103132'))
        p.drawRoundedRect(rect,13,13)
        graph=QRectF(24,52,self.width()-48,self.height()-71)
        for y in [0.25,0.5,0.75]:
            p.setPen(QPen(QColor(127,177,207,18),1,Qt.DashLine))
            p.drawLine(QPointF(graph.left(),graph.top()+graph.height()*y),
                       QPointF(graph.right(),graph.top()+graph.height()*y))
        valid=[v for v in self.samples if v is not None]
        if len(valid)>=2:
            bottom=max(0,min(valid)-12);top=max(bottom+25,max(valid)+12)
            points=[]
            for i,v in enumerate(self.samples):
                if v is None: continue
                x=graph.left()+i/max(1,len(self.samples)-1)*graph.width()
                y=graph.bottom()-(v-bottom)/(top-bottom)*graph.height()
                points.append(QPointF(x,y))
            if len(points)>=2:
                trace=QPainterPath(points[0])
                for point in points[1:]:trace.lineTo(point)
                area=QPainterPath(trace);area.lineTo(points[-1].x(),graph.bottom())
                area.lineTo(points[0].x(),graph.bottom());area.closeSubpath()
                grad=QLinearGradient(0,graph.top(),0,graph.bottom())
                fade=QColor(self.tint);fade.setAlpha(42);grad.setColorAt(0,fade)
                fade.setAlpha(3);grad.setColorAt(1,fade)
                p.fillPath(area,grad)
                faded=QColor(self.tint);faded.setAlpha(90)
                p.setPen(QPen(faded,2));p.drawPath(trace)
        p.setPen(QColor('#bed8e9'));p.setFont(QFont('Noto Sans',11,QFont.DemiBold))
        p.drawText(QRectF(22,14,self.width()-44,28),Qt.AlignLeft|Qt.AlignVCenter,self.label)
        p.setPen(QColor('#2ce1fb'));p.setFont(QFont('Noto Sans',31,QFont.Bold))
        shown=(f'{self.value:.1f} °C'.replace('.',',') if self.value is not None else 'Indisponível')
        p.drawText(QRectF(15,62,self.width()-30,self.height()-78),Qt.AlignCenter,shown)
        p.end()


class Window(QMainWindow):
 def __init__(self):
    super().__init__()
    self.setWindowTitle('Stellar App Monitor');self.setFixedSize(1120,820)
    self.job=None;self.selected_port=None
    center=QWidget();self.setCentralWidget(center)
    full=QHBoxLayout(center);full.setContentsMargins(0,0,0,0);full.setSpacing(0)
    sidebar=QFrame();sidebar.setObjectName('side');sidebar.setFixedWidth(230)
    nav=QVBoxLayout(sidebar);nav.setContentsMargins(14,25,14,18);nav.setSpacing(10)
    nav.addWidget(CometBrand());nav.addSpacing(7)
    self.stack=QStackedWidget();self.nav=[]
    labels=[('⌂','Visão geral'),('⚙','Serviço'),('⌁','Dispositivos USB'),('⇧','Firmware'),('≡','Diagnóstico'),('↻','Atualizações')]
    for idx,(ico,name) in enumerate(labels):
        b=QPushButton(f'{ico}   {name}');b.setObjectName('nav');b.setCheckable(True)
        b.clicked.connect(lambda _,i=idx:self.page(i));nav.addWidget(b);self.nav.append(b)
    nav.addStretch()
    main=QWidget();column=QVBoxLayout(main);column.setContentsMargins(23,16,23,12);column.setSpacing(7)
    self.header=QLabel('Visão geral');self.header.setObjectName('heading');column.addWidget(self.header)
    column.addWidget(self.stack,1)
    logsbox=QGroupBox('Registro de atividades · visível em todas as telas');ll=QVBoxLayout(logsbox)
    self.logs=QPlainTextEdit();self.logs.setReadOnly(True);self.logs.setMaximumBlockCount(500)
    self.logs.setFixedHeight(116);ll.addWidget(self.logs);column.addWidget(logsbox)
    full.addWidget(sidebar);full.addWidget(main,1)
    self.build_overview();self.build_service();self.build_usb();self.build_firmware();self.build_diagnostics();self.build_updates()
    self.setStyleSheet("""
      QMainWindow,QWidget { background:#0c192b; color:#e8f1fb; font:13px 'Noto Sans'; }
      QFrame#side { background:#13243a;border-right:1px solid #25405c; }
      QLabel#brand { color:#f6fbff; font-size:24px; font-weight:800; }
      QLabel#heading { font-size:28px; font-weight:800; color:#f7fbff; padding-bottom:7px; }
      QGroupBox { background:#14263d; border:1px solid #31506d; border-radius:13px;margin-top:14px;padding-top:9px;font-weight:700; }
      QGroupBox::title { subcontrol-origin:margin;left:13px;padding:0 8px;color:#e8f2fb; font-size:15px; }
      QPushButton { background:#213955;color:#ecf7ff;padding:9px;border:1px solid #365a79;border-radius:9px;min-height:25px;font-weight:650; }
      QPushButton:hover { background:#285578;border-color:#35bff2; }
      QPushButton:disabled { color:#8797a7; background:#18293f; }
      QPushButton#nav { text-align:left; background:transparent; border:0; padding:13px 12px;color:#c0d3ed;font-size:14px; }
      QPushButton#nav:hover { background:#1d344f; }
      QPushButton#nav:checked { background:#194366; border:1px solid #1e97d0;border-left:4px solid #21c3fd;color:white; }
      QPlainTextEdit { background:#071225; border:1px solid #263e58;border-radius:9px;padding:10px;color:#d3e6fa;font-family:monospace;font-size:12px; }
      QComboBox { background:#111f32; border:1px solid #3f6080;border-radius:8px;padding:9px; }
      QProgressBar { background:#0c1727;color:white;border:1px solid #34516d;border-radius:8px;text-align:center;min-height:26px; }
      QProgressBar::chunk { background:#12b6df;border-radius:7px; }
    """)
    self.page(0);self.log('Aplicativo inicializado.')
    self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(3000)
    self.refresh_usb();self.refresh()
 def log(self,msg):self.logs.appendPlainText(f"[{datetime.now():%H:%M:%S}] {msg}")
 def page(self,index):
    self.stack.setCurrentIndex(index)
    self.header.setText(['Visão geral','Serviço','Dispositivos USB','Firmware','Diagnóstico','Atualizações'][index])
    for i,b in enumerate(self.nav):b.setChecked(i==index)
    if index==4:self.diagnose()
 def panel(self,lay,name):
    g=QGroupBox(name);v=QVBoxLayout(g);v.setSpacing(10);v.setContentsMargins(14,23,14,12);lay.addWidget(g);return v
 def button(self,lay,title,fn):
    b=QPushButton(title);b.clicked.connect(fn);lay.addWidget(b);return b
 def build_overview(self):
    w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(0,0,0,0);lay.setSpacing(10)
    intro=QLabel('Acompanhe em tempo real o estado do sistema e dos dispositivos.')
    intro.setStyleSheet('color:#91b2d2;font-size:12px;')
    lay.addWidget(intro)
    row=QHBoxLayout();row.setSpacing(12)
    self.temp_cpu=TemperatureCard('CPU · Tctl / k10temp','#1bbdf7')
    self.temp_gpu=TemperatureCard('GPU · AMDGPU edge','#16dbab')
    row.addWidget(self.temp_cpu,1);row.addWidget(self.temp_gpu,1)
    lay.addLayout(row)
    heading=QLabel('Status geral do sistema');heading.setStyleSheet('font-size:19px;font-weight:800;color:#f4f8fd;')
    lay.addWidget(heading)
    grid=QGridLayout();grid.setSpacing(10)
    self.stat={}
    items=[('installed','⚙','Serviço instalado'),('running','▶','Serviço em execução'),('enabled','⏻','Iniciar no login'),('usb','⌁','ESP32 via USB'),('sending','↑','Envio de temperaturas'),('display','▣','Exibição no display')]
    for i,(key,icon,title) in enumerate(items):
        tile=QLabel(icon+'    '+title+'\n●  Verificando...')
        tile.setMinimumHeight(74);tile.setAlignment(Qt.AlignVCenter|Qt.AlignLeft)
        tile.setStyleSheet('background:#102f37;border:1px solid #11645c;border-radius:11px;color:#56eab1;padding:10px;font-weight:700;font-size:13px;')
        grid.addWidget(tile,i//3,i%3);self.stat[key]=(icon+'    '+title,tile)
    lay.addLayout(grid);lay.addStretch(1)
    self.stack.addWidget(w)
 def build_service(self):
    w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(0,0,0,0);lay.setSpacing(13)
    install=self.panel(lay,'Instalação do monitor')
    r=QHBoxLayout();self.button(r,'Instalar / Atualizar serviço',self.install_service);self.button(r,'Remover serviço',self.remove_service);install.addLayout(r)
    control=self.panel(lay,'Controle de execução')
    r=QHBoxLayout()
    for name,op in [('Iniciar','start'),('Parar','stop'),('Reiniciar','restart')]:
      self.button(r,name,lambda _,x=op:self.systemctl(x))
    control.addLayout(r)
    auto=self.panel(lay,'Iniciar automaticamente no login')
    r=QHBoxLayout()
    for name,op in [('Habilitar','enable'),('Desabilitar','disable')]:
      self.button(r,name,lambda _,x=op:self.systemctl(x))
    auto.addLayout(r);lay.addStretch();self.stack.addWidget(w)
 def build_usb(self):
    w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(0,0,0,0)
    box=self.panel(lay,'Placas USB conectadas')
    box.addWidget(QLabel('Selecione a porta física da sua placa ESP32-C3.'))
    self.combo=QComboBox();self.combo.setMinimumHeight(43);box.addWidget(self.combo)
    row=QHBoxLayout()
    self.button(row,'Atualizar lista',self.refresh_usb);self.button(row,'Testar porta',self.test_usb)
    self.button(row,'Usar esta porta',self.save_usb);box.addLayout(row)
    self.button(box,'Ajuda com permissões USB',self.usb_help)
    lay.addStretch();self.stack.addWidget(w)
 def build_firmware(self):
    w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(0,0,0,0)
    box=self.panel(lay,'Atualização do firmware STELLAR')
    note=QLabel('Firmware para ESP32-C3 + GC9A01. O aplicativo baixa e compila automaticamente o firmware oficial na primeira atualização, se necessário.')
    note.setWordWrap(True);box.addWidget(note)
    self.flash_button=self.button(box,'Atualizar firmware',self.flash)
    self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);box.addWidget(self.progress)
    self.flash_status=QLabel('Aguardando ESP32-C3 conectado.');box.addWidget(self.flash_status)
    lay.addStretch();self.stack.addWidget(w)
 def build_diagnostics(self):
    w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(0,0,0,0)
    box=self.panel(lay,'Diagnóstico detalhado')
    self.button(box,'Atualizar verificação',self.diagnose)
    self.diag=QPlainTextEdit();self.diag.setReadOnly(True);box.addWidget(self.diag)
    self.button(box,'Exibir logs recentes do serviço',self.service_logs)
    lay.addStretch();self.stack.addWidget(w)
 def build_updates(self):
    w=QWidget();layout=QVBoxLayout(w);layout.setContentsMargins(0,0,0,0);layout.setSpacing(15)
    info=self.panel(layout,'Atualização do Stellar App Monitor')
    desc=QLabel('Baixe as alterações oficiais do GitHub. Depois aplique a atualização e reinicie o aplicativo.')
    desc.setWordWrap(True);info.addWidget(desc)
    self.update_label=QLabel('Nenhuma atualização verificada nesta sessão.')
    info.addWidget(self.update_label)
    row=QHBoxLayout()
    self.fetch_button=self.button(row,'ATUALIZAR',self.fetch_update)
    self.apply_button=self.button(row,'APLICAR ATUALIZAÇÃO',self.apply_update)
    self.apply_button.setEnabled(False);info.addLayout(row)
    self.update_progress=QProgressBar();self.update_progress.setRange(0,100)
    self.update_progress.setValue(0);info.addWidget(self.update_progress)
    foot=QLabel('Durante o download, a porcentagem segue o progresso real informado pelo Git. A instalação de dependências mostra suas etapas nos logs.')
    foot.setWordWrap(True);info.addWidget(foot)
    layout.addStretch();self.stack.addWidget(w)

 def fetch_update(self):
    if self.job and self.job.isRunning():
        self.error('Atualização','Outra operação está em andamento.');return
    if not (BASE/'.git').is_dir():
        self.error('Atualização','Instalação sem Git. Reinstale pelo comando oficial do README.');return
    rc,dirty=command(['git','-C',str(BASE),'status','--porcelain','--untracked-files=no'],15)
    if rc or dirty:
        self.log('Diagnóstico Git: '+(dirty or 'git status retornou código '+str(rc)))
        self.error('Atualização','Há modificações em arquivos versionados ou o Git falhou. Arquivos gerados pelo aplicativo não bloqueiam atualizações. Consulte os logs.')
        return
    self.fetch_button.setEnabled(False);self.apply_button.setEnabled(False)
    self.update_progress.setValue(0);self.update_label.setText('Baixando atualização...')
    def task(j):
        argv=['git','-C',str(BASE),'fetch','--progress','origin','main']
        j.emit('Baixando atualizações de origem confiável: GitHub oficial.')
        p=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=0)
        buf=''
        while True:
            byte=p.stdout.read(1)
            if not byte:break
            char=byte.decode('utf-8','replace')
            if char in '\r\n':
                if buf.strip():
                    j.emit(buf.strip()[-220:])
                    matches=re.findall(r'(?:Receiving objects|Resolving deltas):\s*(\d+)%',buf)
                    if matches:j.progress.emit(min(95,int(matches[-1])))
                buf=''
            else:buf=(buf+char)[-700:]
        if p.wait()!=0:raise RuntimeError('Falha ao baixar atualização do GitHub.')
        j.progress.emit(100)
        rc,head=command(['git','-C',str(BASE),'rev-parse','HEAD'],10)
        rc,remote=command(['git','-C',str(BASE),'rev-parse','FETCH_HEAD'],10)
        if head==remote:j.emit('O Stellar App Monitor já está na versão mais recente.')
        else:
            rc,out=command(['git','-C',str(BASE),'merge-base','--is-ancestor',head,remote],10)
            if rc:raise RuntimeError('Histórico Git divergente; atualização automática não segura.')
            j.emit('Atualização disponível: '+remote[:10])
    def finished(ok,msg):
        self.fetch_button.setEnabled(True)
        if not ok:
            self.update_label.setText('Erro no download — consulte os logs.')
            return
        old=command(['git','-C',str(BASE),'rev-parse','HEAD'],10)[1]
        new=command(['git','-C',str(BASE),'rev-parse','FETCH_HEAD'],10)[1]
        can_apply=bool(old and new and old!=new)
        self.apply_button.setEnabled(can_apply)
        self.update_label.setText('Atualização disponível — clique Aplicar atualização.' if can_apply else 'Aplicativo atualizado.')
    self.run_job('Buscar atualização do aplicativo',task,finished,progressbar=self.update_progress)

 def apply_update(self):
    if self.job and self.job.isRunning():
        self.error('Atualização','Existe outra operação em andamento.');return
    if not self.apply_button.isEnabled():return
    if QMessageBox.question(self,'Aplicar atualização','Instalar a versão baixada e reiniciar o Stellar App Monitor?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
    self.apply_button.setEnabled(False);self.fetch_button.setEnabled(False)
    self.update_label.setText('Aplicando atualização...')
    def task(j):
        rc,dirty=command(['git','-C',str(BASE),'status','--porcelain','--untracked-files=no'],15)
        if rc or dirty:raise RuntimeError('Arquivos versionados modificados ou Git indisponível. Atualização cancelada: '+(dirty or str(rc)))
        j.emit('Aplicando commit baixado...')
        j.cmd(['git','-C',str(BASE),'merge','--ff-only','FETCH_HEAD'],60)
        j.emit('Atualizando dependências Python...')
        j.cmd([sys.executable,'-m','pip','install','--disable-pip-version-check','-r',str(BASE/'requirements.txt')],240)
        j.emit('Aplicação concluída. Reiniciando...')
    def finished(ok,msg):
        if not ok:
            self.fetch_button.setEnabled(True)
            self.update_label.setText('Falha ao aplicar atualização — consulte os logs.')
            return
        script=BASE/'abrir-stellar.sh'
        args=[str(script)] if script.is_file() else [sys.executable,str(BASE/'main.py')]
        try:
            subprocess.Popen(args,cwd=str(BASE),start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.log('Novo processo iniciado; encerrando esta versão.')
            QApplication.instance().quit()
        except Exception as e:
            self.fetch_button.setEnabled(True)
            self.error('Reinício',str(e))
    self.run_job('Aplicar atualização do aplicativo',task,finished,progressbar=self.update_progress)

 def refresh(self):
    a,an=sensor('k10temp');b,bn=sensor('amdgpu')
    self.temp_cpu.update_reading(a,f'CPU · {an}')
    self.temp_gpu.update_reading(b,f'GPU · {bn}')
    exists=UNIT_PATH.exists()
    rc,run=command(['systemctl','--user','is-active',UNIT],5)
    rc,en=command(['systemctl','--user','is-enabled',UNIT],5)
    connected=ports()
    service_log=command(['journalctl','--user','-u',UNIT,'--since','20 seconds ago','--no-pager','-n','12'],5)[1]
    values={'installed':(exists,'Instalado' if exists else 'Não instalado'),
            'running':(run=='active','Ativo' if run=='active' else 'Parado'),
            'enabled':(en=='enabled','Habilitado' if en=='enabled' else 'Desabilitado'),
            'usb':(bool(connected),'Conectado' if connected else 'Desconectado'),
            'sending':('CPU:' in service_log and 'GPU:' in service_log,'Ver logs' if not service_log else ('Enviando' if 'CPU:' in service_log and 'GPU:' in service_log else 'Não confirmado')),
            'display':(None,'Não confirmada')}
    for key,(ok,val) in values.items():
      name,tile=self.stat[key];color='#86efac' if ok else ('#fbbf24' if ok is None else '#fda4af')
      tile.setText(name+'\n●  '+val);tile.setStyleSheet('background:'+('#332f21' if ok is None else '#102f37' if ok else '#382834')+';border:1px solid '+('#9c8037' if ok is None else '#147b6d' if ok else '#8f4355')+';color:'+color+';border-radius:11px;padding:10px;font-weight:700;font-size:13px;')
 def refresh_usb(self):
    current=self.combo.currentData() if self.combo.count() else None
    self.combo.clear();lst=ports()
    for x in lst:self.combo.addItem(f'{x.device} — {x.description} ({x.vid:04x}:{x.pid:04x})',x.device)
    if current:
      for i in range(self.combo.count()):
        if self.combo.itemData(i)==current:self.combo.setCurrentIndex(i);break
    self.log(f'USB: {len(lst)} dispositivo(s) físico(s) identificado(s).')
 def usb(self):
    port=self.combo.currentData()
    if not port or port not in [x.device for x in ports()]:raise RuntimeError('Nenhuma placa USB selecionada/conectada.')
    return port
 def test_usb(self):
    try:
      import serial
      port=self.usb()
      with serial.Serial(port,115200,timeout=1):pass
      self.log(f'USB: acesso OK em {port}. Isto não verifica firmware/display.')
    except Exception as e:self.error('USB',str(e))
 def save_usb(self):
    try:
      port=self.usb();cfg=HOME/'.config/bc250-display'
      cfg.mkdir(parents=True,exist_ok=True)
      (cfg/'port').write_text(port+'\n')
      self.log(f'Porta selecionada e salva: {port}')
    except Exception as e:self.error('USB',str(e))
 def usb_help(self):
    self.log('USB: para corrigir permissão, verifique ls -l /dev/ttyACM0 e os grupos do usuário.')
    QMessageBox.information(self,'Permissão USB','Verifique o grupo proprietário da porta com ls -l /dev/ttyACM0 ou ttyUSB0. Adicione o usuário ao grupo apropriado e entre novamente na sessão. Não use chmod 777.')
 def run_job(self,label,fn,done=None,progressbar=None):
    if self.job and self.job.isRunning():self.error('Operação em andamento','Conclua a operação anterior.');return
    self.log('Início: '+label)
    self.job=Job(fn);self.job.line.connect(self.log)
    self.job.progress.connect(lambda value:(progressbar or self.progress).setValue(value))
    def complete(ok,msg):
      self.log(('SUCESSO: ' if ok else 'ERRO: ')+label+('' if ok else ' — '+msg))
      if done:done(ok,msg)
      if not ok:QMessageBox.warning(self,'Stellar App Monitor',msg)
      self.refresh()
    self.job.done.connect(complete);self.job.start()
 def systemctl(self,op):
    if not UNIT_PATH.exists() and op not in ('stop',):
      self.error('Serviço','Serviço não instalado. Instale primeiro.');return
    self.run_job('Serviço: '+op,lambda j:j.cmd(['systemctl','--user',op,UNIT]))
 def install_service(self):
    def task(j):
      j.cmd(['bash',str(BASE/'install-service.sh')],180)
    self.run_job('Instalar/Atualizar serviço',task)
 def remove_service(self):
    if QMessageBox.question(self,'Remover serviço','Remover o serviço do usuário (sem apagar firmware)?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
    def task(j):
      command(['systemctl','--user','disable','--now',UNIT],20)
      if UNIT_PATH.exists():UNIT_PATH.unlink()
      j.cmd(['systemctl','--user','daemon-reload'])
    self.run_job('Remover serviço',task)
 def error(self,title,msg):self.log('ERRO: '+title+' — '+msg);QMessageBox.warning(self,title,msg)
 def diagnose(self):
    a,an=sensor('k10temp');b,bn=sensor('amdgpu')
    self.diag.setPlainText(f'CPU: {a} °C ({an})\nGPU: {b} °C ({bn})\nServiço: {UNIT_PATH}\nPortas USB:\n'+'\n'.join(x.device+' '+x.description for x in ports()))
    self.log('Diagnóstico dos sensores e portas atualizado.')
 def service_logs(self):
    _,out=command(['journalctl','--user','-u',UNIT,'-n','50','--no-pager'],10)
    self.diag.setPlainText(out);self.log('Logs recentes do serviço carregados.')
 def flash(self):
    try:port=self.usb()
    except Exception as e:self.error('Placa não conectada',str(e));self.page(2);return
    if QMessageBox.question(self,'Atualizar firmware',f'Confirmar gravação no ESP32-C3 conectado em {port}?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
    self.progress.setValue(0);self.flash_status.setText('Preparando firmware...')
    self.flash_button.setEnabled(False)
    def task(j):
      if not FIRMWARE.exists():
        j.emit('Firmware não encontrado localmente: compilação automática iniciada.')
        j.cmd(['bash',str(BASE/'prepare-firmware.sh')],1500)
      if not FIRMWARE.exists():raise RuntimeError('Arquivo de firmware não foi gerado.')
      if not Path(port).exists():raise RuntimeError('A placa foi desconectada.')
      _,active=command(['systemctl','--user','is-active',UNIT],8)
      restore=(active=='active')
      if restore:j.cmd(['systemctl','--user','stop',UNIT])
      try:
        j.emit('Verificando chip ESP32-C3 antes da gravação...')
        j.cmd([sys.executable,'-m','esptool','--chip','esp32c3','--port',port,'--baud','115200','read-mac'],35)
        j.emit('Gravando firmware...')
        p=subprocess.Popen([sys.executable,'-m','esptool','--chip','esp32c3','--port',port,'--baud','115200','write-flash','0x0',str(FIRMWARE)],
             stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=0)
        buffer=''
        while True:
          ch=p.stdout.read(1)
          if not ch:break
          t=ch.decode('utf-8',errors='replace')
          if t in '\r\n':
            if buffer.strip():
              j.emit(buffer.strip()[-200:])
              matches=re.findall(r'(\d{1,3})\s*%',buffer)
              if matches:j.progress.emit(min(99,int(matches[-1])))
            buffer=''
          else:buffer=(buffer+t)[-500:]
        rc=p.wait()
        if rc:raise RuntimeError(f'esptool retornou erro {rc}')
        j.progress.emit(100)
      finally:
        if restore:
          rc,out=command(['systemctl','--user','start',UNIT],20)
          j.emit('Serviço restaurado.' if rc==0 else 'ATENÇÃO: falhou ao restaurar o serviço: '+out)
    def finished(ok,msg):
      self.flash_button.setEnabled(True)
      self.flash_status.setText('Firmware atualizado (100%)' if ok else 'Falha na gravação; consulte os logs.')
    self.run_job('Atualizar firmware em '+port,task,finished)

def main():
 app=QApplication(sys.argv);w=Window();w.show();sys.exit(app.exec())
if __name__=='__main__':main()
