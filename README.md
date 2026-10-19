# Stellar App Monitor

![Prévia ilustrativa da tela inicial do Stellar App Monitor](docs/stellar-app-monitor-visao-geral.svg)

> Prévia ilustrativa da interface. As temperaturas e os estados exibidos são exemplos; no aplicativo, os valores vêm do sistema.

Aplicativo gráfico para monitoramento de temperaturas da **AMD BC250** no **Bazzite** e **CachyOS**, com configuração de serviço `systemd --user`, seleção de ESP32-C3 e atualização do firmware do display **GC9A01**.

## Instalação em um comando

Abra um terminal na sessão gráfica do Linux e execute:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/isaacalvex/AMD-BC250-Display-Status-Bazzite-CachyOS/main/install-app.sh)"
```

O instalador baixa o aplicativo, cria um ambiente Python isolado, instala as bibliotecas, cria um atalho em **Aplicativos** e tenta criar também na **Área de Trabalho**; em seguida abre o Stellar App Monitor. Não execute com `sudo`. É necessário ter Git, Python 3 com `venv`, conexão à Internet e sessão gráfica. Em alguns desktops será necessário escolher **Permitir execução** no atalho.

## Páginas do aplicativo

- **Visão geral:** CPU/GPU em tempo real, status de serviço, login, USB e envio de temperaturas.
- **Serviço:** instalar/remover, iniciar/parar/reiniciar e habilitar/desabilitar no login.
- **Dispositivos USB:** escolher porta e testar comunicação/permissões.
- **Firmware:** atualizar o ESP32-C3 com uma confirmação e indicador percentual, sem selecionar manualmente o arquivo.
- **Diagnóstico:** registros do serviço e testes dos sensores.

Logs de cada operação ficam visíveis na parte inferior em todas as páginas.

## Preparar monitoramento

1. Abra o app pelo menu de Aplicativos ou atalho da Área de Trabalho.
2. Na página **Serviço**, clique **Instalar/Atualizar**.
3. Conecte a placa ESP32-C3 com GC9A01, selecione a porta em **Dispositivos USB**, clique **Usar esta porta**.
4. Inicie o serviço e confira as temperaturas na **Visão geral**.
5. Em **Firmware**, clique **Atualizar firmware** quando precisar regravar. A primeira atualização prepara automaticamente o ambiente Arduino CLI e compila o firmware oficial no próprio computador, o que requer Internet e espaço em disco. As seguintes atualizações reutilizam o binário compilado. **Não desconecte a placa durante a gravação.**

O firmware é destinado à pinagem do projeto original (MOSI 7, SCLK 6, CS 10, DC 2, BL 3). Placas ESP32-C3 com outra tela/pinagem podem precisar de firmware diferente. O aplicativo valida o tipo de chip via esptool.

### Problemas conhecidos

- USB não disponível: conecte a placa, escolha uma porta física válida; se houver erro de permissão, ajuste seu grupo de acesso e entre novamente na sessão.
- CPU/GPU indisponível: drivers e interfaces `hwmon` variam; verifique **Diagnóstico**.
- O envio de pacotes não confirma, sozinho, que a tela exibiu a imagem.

## Capturas de tela

Capturas reais dependem da execução no hardware e serão adicionadas após validação no CachyOS/Bazzite. O código e o fluxo de instalação foram preparados; os testes de gravação em diferentes placas ainda não foram concluídos.
