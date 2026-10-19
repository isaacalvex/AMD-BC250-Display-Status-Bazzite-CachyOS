# AMD BC250 Display Status — Bazzite

Versão dedicada ao **Bazzite OS** (Fedora Atomic). Instala o monitor serial para ESP32-C3 / GC9A01 como **serviço systemd do usuário**, sem modificar a imagem imutável do sistema.

## Instalação

```bash
git clone https://github.com/isaacalvex/AMD-BC250-Display-Status-Bazzite.git
cd AMD-BC250-Display-Status-Bazzite
bash setup.sh
```

> O link acima só funcionará após a criação do novo repositório e o envio destes arquivos. Não rode scripts de um repositório ainda não publicado.

É necessário `git`, `python3` com `venv` e acesso à internet para instalar `pyserial`. O comando `sensors` também precisa estar disponível; teste com `sensors`. O instalador não usa `dnf install` nem modifica pacotes do sistema base.

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

O script **não envia temperaturas simuladas**. CPU usa a leitura `Tctl` de `sensors` e GPU usa hwmon `amdgpu` ou `sensors`. O formato enviado é `CPU:46.6;GPU:44.0` a 115200 baud. Se não houver ambas as leituras, não há pacote.

## Atualização

Rode `bash setup.sh` novamente dentro do repositório clonado. Para remover:

```bash
systemctl --user disable --now bc250-display.service
rm -f ~/.config/systemd/user/bc250-display.service
systemctl --user daemon-reload
rm -rf ~/.local/share/bc250-display
```
