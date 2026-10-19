# AMD BC250 Display Status — Bazzite

Versão dedicada ao **Bazzite OS** (Fedora Atomic). Instala o monitor serial para ESP32-C3 / GC9A01 como **serviço systemd do usuário**, sem modificar a imagem imutável do sistema.

## Como instalar o serviço

Siga os passos abaixo no **terminal do Bazzite**. Não execute os comandos com `sudo`, exceto quando indicado para corrigir permissões.

**Repositório oficial desta versão:** https://github.com/isaacalvex/AMD-BC250-Display-Status-BazziteOS

### Passo 1 — Baixe o projeto

Execute:

```bash
git clone https://github.com/isaacalvex/AMD-BC250-Display-Status-BazziteOS.git
```

### Passo 2 — Entre na pasta do projeto

Execute:

```bash
cd AMD-BC250-Display-Status-BazziteOS
```

### Passo 3 — Instale e ative o serviço

Execute:

```bash
bash setup.sh
```

O instalador cria o ambiente virtual Python, instala o `pyserial`, registra o serviço `bc250-display.service` e o habilita e inicia automaticamente na **sessão do usuário**.

### Passo 4 — Conecte o ESP32 e confira o serviço

O ESP32-C3 precisa estar conectado via USB e com o firmware gravado conforme a seção **Firmware** abaixo. Para verificar o estado do serviço, execute:

```bash
systemctl --user status bc250-display.service
```

O estado `active (running)` indica que o processo está em execução; **não garante**, por si só, que temperaturas estejam chegando à tela.

### Passo 5 — Acompanhe o envio das temperaturas

Execute:

```bash
journalctl --user -u bc250-display.service -f
```

Se CPU e GPU forem identificadas e o ESP32 estiver conectado corretamente, os logs mostrarão as leituras enviadas. Pressione **Ctrl+C** para sair dos logs sem desligar o serviço.

### Passo 6 — Confirme a inicialização automática

Execute:

```bash
systemctl --user is-enabled bc250-display.service
```

A resposta `enabled` indica que o serviço está configurado para iniciar automaticamente na sessão do usuário. Não é garantida a execução antes do login.

### Comandos úteis

**Iniciar o serviço manualmente:**

```bash
systemctl --user start bc250-display.service
```

**Reiniciar o serviço:**

```bash
systemctl --user restart bc250-display.service
```

**Parar o serviço:**

```bash
systemctl --user stop bc250-display.service
```

**Requisitos:** `git`, `python3` com `venv`, acesso à internet e sensores de temperatura acessíveis pelo `hwmon` do kernel ou pelo comando `sensors`. O instalador não usa `dnf install` nem altera pacotes da imagem imutável do Bazzite.

## Firmware

Grave no ESP32-C3 o `stellar_monitor.ino` do [projeto original](https://github.com/isaacalvex/AMD-BC250-Display-Status/blob/main/stellar_monitor.ino), com **USB CDC On Boot: Enabled**. O arquivo de firmware não foi modificado nesta variante Bazzite.

## Serviço e diagnóstico

```bash
systemctl --user status bc250-display.service
journalctl --user -u bc250-display.service -f
systemctl --user restart bc250-display.service
sensors
ls -l /dev/serial/by-id/
```

O serviço inicia **com a sessão do usuário**; o modo Gaming do Bazzite também utiliza sessões do usuário. Não é garantido que rode antes do login. Para verificar o ESP32, confirme que ele aparece em `/dev/ttyACM*`, `/dev/ttyUSB*` ou `/dev/serial/by-id/`.

Se ocorrer `Permission denied`, verifique o grupo proprietário da porta com `ls -l /dev/ttyACM0`. Se for `dialout`, execute `sudo usermod -aG dialout "$USER"` e depois faça logout/login. Outros grupos podem ser usados dependendo das regras udev.

O ESP32 permanece na animação STELLAR até receber o primeiro pacote válido de CPU e GPU. Depois disso, atualiza aproximadamente a cada segundo. Se ficar mais de 5 segundos sem novos pacotes, volta à animação. O serviço inicia na sessão do usuário (não necessariamente durante o boot, antes do login).

O script **não envia temperaturas simuladas**. CPU usa `k10temp` do `hwmon` (quando disponível), com alternativa `Tctl` de `sensors`; GPU usa `hwmon` `amdgpu` ou `sensors`. O formato enviado é `CPU:46.6;GPU:44.0` a 115200 baud. Se não houver ambas as leituras, não há pacote.

## Atualização

Rode `bash setup.sh` novamente dentro do repositório clonado. Para remover:

```bash
systemctl --user disable --now bc250-display.service
rm -f ~/.config/systemd/user/bc250-display.service
systemctl --user daemon-reload
rm -rf ~/.local/share/bc250-display
```

### Mais de uma porta serial conectada

Se houver vários dispositivos USB seriais e o monitor conectar no dispositivo errado, escolha explicitamente a porta criando uma configuração no serviço:

```bash
systemctl --user edit bc250-display.service
```

Acrescente no editor:

```ini
[Service]
Environment=BC250_SERIAL_PORT=/dev/ttyACM0
```

Substitua a porta pela correta, salve e execute:

```bash
systemctl --user daemon-reload
systemctl --user restart bc250-display.service
```

A porta real pode ser identificada com `ls -l /dev/serial/by-id/`. Prefira um caminho persistente de `/dev/serial/by-id/` quando disponível.
