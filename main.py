#!/usr/bin/env python3
"""Stellar App Monitor — PySide6 desktop client for AMD BC250 / ESP32-C3."""
import os, sys, re, glob, time, subprocess, threading, urllib.request
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QThread
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
class Window(QMainWindow):
 def __init__(self):
    super().__init__()
    self.setWindowTitle('Stellar App Monitor');self.setFixedSize(1120,820)
    self.job=None;self.selected_port=None
    center=QWidget();self.setCentralWidget(center)
    full=QHBoxLayout(center);full.setContentsMargins(0,0,0,0);full.setSpacing(0)
    sidebar=QFrame();sidebar.setObjectName('side');sidebar.setFixedWidth(220)
    nav=QVBoxLayout(sidebar);nav.setContentsMargins(14,26,14,18);nav.setSpacing(10)
    title=QLabel('✦  STELLAR');title.setObjectName('brand');nav.addWidget(title)
    nav.addWidget(QLabel('App Monitor'));nav.addSpacing(25)
    self.stack=QStackedWidget();self.nav=[]
    labels=[('⌂','Visão geral'),('⚙','Serviço'),('⌁','Dispositivos USB'),('⇧','Firmware'),('≡','Diagnóstico')]
    for idx,(ico,name) in enumerate(labels):
        b=QPushButton(f'{ico}   {name}');b.setObjectName('nav');b.setCheckable(True)
        b.clicked.connect(lambda _,i=idx:self.page(i));nav.addWidget(b);self.nav.append(b)
    nav.addStretch()
    main=QWidget();column=QVBoxLayout(main);column.setContentsMargins(24,22,24,17);column.setSpacing(10)
    self.header=QLabel('Visão geral');self.header.setObjectName('heading');column.addWidget(self.header)
    column.addWidget(self.stack,1)
    logsbox=QGroupBox('Registro de atividades · visível em todas as telas');ll=QVBoxLayout(logsbox)
    self.logs=QPlainTextEdit();self.logs.setReadOnly(True);self.logs.setMaximumBlockCount(500)
    self.logs.setFixedHeight(138);ll.addWidget(self.logs);column.addWidget(logsbox)
    full.addWidget(sidebar);full.addWidget(main,1)
    self.build_overview();self.build_service();self.build_usb();self.build_firmware();self.build_diagnostics()
    self.setStyleSheet("""
      QMainWindow,QWidget{background:#101827;color:#e9f1fc;font-size:13px;font-family:'Noto Sans'}
      QFrame#side{background:#17273c;border-right:1px solid #30465e}
      QLabel#brand{color:#67e8f9;font-size:23px;font-weight:bold}
      QLabel#heading{font-size:25px;font-weight:bold}
      QGroupBox{background:#1d3047;border:1px solid #334d6b;border-radius:11px;margin-top:16px;padding-top:8px;font-weight:bold}
      QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 7px;color:#bce7f8}
      QPushButton{background:#294562;color:white;padding:10px;border-radius:8px;min-height:23px;border:1px solid #395e80}
      QPushButton:hover{background:#356185} QPushButton:disabled{color:#8896ad;background:#233044}
      QPushButton#nav{text-align:left;background:transparent;border:0;padding:13px}
      QPushButton#nav:checked{background:#235272;border-left:3px solid #67e8f9}
      QPlainTextEdit,QComboBox{background:#0c1626;border:1px solid #405977;border-radius:7px;padding:8px}
      QProgressBar{background:#0c1626;color:white;border-radius:8px;text-align:center;min-height:25px}
      QProgressBar::chunk{background:#1498c6;border-radius:8px}
    """)
    self.page(0);self.log('Aplicativo inicializado.')
    self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(3000)
    self.refresh_usb();self.refresh()
 def log(self,msg):self.logs.appendPlainText(f"[{datetime.now():%H:%M:%S}] {msg}")
 def page(self,index):
    self.stack.setCurrentIndex(index)
    self.header.setText(['Visão geral','Serviço','Dispositivos USB','Firmware','Diagnóstico'][index])
    for i,b in enumerate(self.nav):b.setChecked(i==index)
    if index==4:self.diagnose()
 def panel(self,lay,name):
    g=QGroupBox(name);v=QVBoxLayout(g);v.setSpacing(10);v.setContentsMargins(14,23,14,12);lay.addWidget(g);return v
 def button(self,lay,title,fn):
    b=QPushButton(title);b.clicked.connect(fn);lay.addWidget(b);return b
 def build_overview(self):
    w=QWidget();lay=QVBoxLayout(w);lay.setContentsMargins(0,0,0,0);lay.setSpacing(8)
    temps=self.panel(lay,'Temperaturas em tempo real')
    row=QHBoxLayout();self.temp_cpu=QLabel('CPU  —');self.temp_gpu=QLabel('GPU  —')
    for l in (self.temp_cpu,self.temp_gpu):
      l.setAlignment(Qt.AlignCenter);l.setStyleSheet('font-size:25px;font-weight:bold;color:#67e8f9;padding:11px;background:#203950;border-radius:9px');row.addWidget(l)
    temps.addLayout(row);self.temp_desc=QLabel('Aguardando leituras');temps.addWidget(self.temp_desc)
    statuses=self.panel(lay,'Status geral do sistema')
    grid=QGridLayout();grid.setSpacing(9)
    self.stat={}
    for i,(key,title) in enumerate([('installed','✓  Serviço instalado'),('running','◉  Serviço em execução'),('enabled','⏻  Iniciar no login'),('usb','⌁  ESP32 via USB'),('sending','↑  Envio de temperaturas'),('display','▣  Exibição no display')]):
      tile=QLabel(title+'\nVerificando...');tile.setMinimumHeight(60);tile.setAlignment(Qt.AlignCenter)
      tile.setStyleSheet('background:#253d55;color:#e7f1fd;border-radius:9px;padding:7px')
      grid.addWidget(tile,i//2,i%2);self.stat[key]=(title,tile)
    statuses.addLayout(grid);lay.addStretch();self.stack.addWidget(w)
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
 def refresh(self):
    a,an=sensor('k10temp');b,bn=sensor('amdgpu')
    self.temp_cpu.setText(f'CPU  {a:.1f} °C' if a is not None else 'CPU  indisponível')
    self.temp_gpu.setText(f'GPU  {b:.1f} °C' if b is not None else 'GPU  indisponível')
    self.temp_desc.setText(f'{an}  |  {bn}')
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
      tile.setText(name+'\n'+val);tile.setStyleSheet('background:#253d55;color:'+color+';border-radius:9px;padding:7px')
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
 def run_job(self,label,fn,done=None):
    if self.job and self.job.isRunning():self.error('Operação em andamento','Conclua a operação anterior.');return
    self.log('Início: '+label)
    self.job=Job(fn);self.job.line.connect(self.log)
    self.job.progress.connect(lambda value:self.progress.setValue(value))
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
