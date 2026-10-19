# AMD BC250 Display Status — Bazzite

Versão dedicada ao **Bazzite OS** (Fedora Atomic). Instala o monitor serial para ESP32-C3 / GC9A01 como **serviço systemd do usuário**, sem modificar a imagem imutável do sistema.

## Como instalar o serviço

Abra o terminal do **Bazzite** e execute o comando abaixo para baixar o projeto, entrar na pasta e instalar o serviço:

```bash
git clone https://github.com/isaacalvex/AMD-BC250-Display-Status-Bazzite.git && cd AMD-BC250-Display-Status-Bazzite && bash setup.sh
```

> **Atenção:** o comando acima só funcionará depois que este repositório for publicado no GitHub com os arquivos do projeto.

O instalador configura um ambiente virtual Python, instala o `pyserial`, cria o serviço `bc250-display.service` e o habilita para iniciar automaticamente **na sessão do usuário**. Não é necessário iniciar o programa manualmente a cada login. A execução antes do login não é garantida.

**Requisitos:** `git`, `python3` com suporte a `venv`, conexão com a internet e o comando `sensors` disponível no sistema. O instalador não usa `dnf install` nem altera os pacotes do sistema base.

### Como iniciar e verificar o serviço

Para iniciar imediatamente (caso não esteja em execução):

```bash
systemctl --user start bc250-display.service
```

Para verificar o estado do serviço:

```bash
systemctl --user status bc250-display.service
```

Para acompanhar os dados e possíveis erros em tempo real:

```bash
journalctl --user -u bc250-display.service -f
```

Para reiniciar o serviço:

```bash
systemctl --user restart bc250-display.service
```

Para confirmar que ele iniciará automaticamente nas próximas sessões:

```bash
systemctl --user is-enabled bc250-display.service
```

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
