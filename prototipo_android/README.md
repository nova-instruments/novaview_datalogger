# NovaView Datalogger para Android

Consulte os registros do equipamento no tablet, mesmo sem internet. Esta versão
é desenvolvida nesta pasta separada; a versão Windows permanece independente.

## Instalação e abertura

1. Copie **[NovaView-Android-ARM64.apk](dist/NovaView-Android-ARM64.apk)** para o tablet.
2. Abra o APK pelo aplicativo de arquivos e escolha **Instalar** ou **Atualizar**.
3. Abra **NovaView Datalogger**.
4. Após a extração dos dados da máquina, conecte o pendrive Nova Instruments
   ao tablet e toque em **Abrir arquivo**. Selecione um TXT ou DB do equipamento.
   Também é possível abrir um arquivo salvo no próprio tablet.

Se a versão anterior já está instalada, use este APK como atualização. O nome
do aplicativo passa de NovaView Android para NovaView Datalogger.
Mais detalhes em [INSTALAR_NO_TABLET.md](INSTALAR_NO_TABLET.md).

## O que você pode fazer

| Aba | Funcionalidades |
| --- | --- |
| **Painel** | Consultar o gráfico, temperaturas média, mínima e máxima, setpoint médio quando disponível e contadores de alertas. |
| **Dados** | Consultar todos os registros, buscar por texto, filtrar por tipo de alarme e faixa de temperatura, e ordenar por data. |
| **Alarmes** | Consultar todos os registros com alerta, aplicar os mesmos filtros e abrir os detalhes. |

O número de série aparece acima das abas. Em **Período → Alterar**, confira o
início e o fim do datalogger e escolha as datas e os horários desejados. Só são
oferecidos dias com registros e horários dentro dos limites do arquivo. Toque
em **Aplicar período**; a seleção vale para as três abas. **Completo** restaura
todo o arquivo.

No gráfico, arraste para mover, use dois dedos para aproximar e toque para ver
o registro. **Restaurar** retorna ao período selecionado. Quando disponíveis,
as curvas de setpoint e o estado da porta podem ser mostrados junto à principal.

Nas tabelas, toque em **Filtros**, combine a busca, o tipo de alarme e os limites
de temperatura, e toque em **Aplicar**. Os limites aceitam números negativos
e vírgula ou ponto decimal; deixar um campo vazio remove esse limite.
**Limpar** remove os filtros daquela aba. O período escolhido continua aplicado.
Os resultados são apresentados em páginas de 50 registros. Deslize a tabela
para os lados para consultar todas as colunas e toque em uma linha para ver
os detalhes, incluindo outras medições quando estiverem no arquivo.

## Câmara Fria e Freezer

O aplicativo identifica o tipo pela temperatura do arquivo. No Painel, você
pode conferir a identificação e escolher manualmente **Câmara Fria** ou
**Freezer −30 °C**, se necessário.

- **Câmara Fria:** alerta abaixo de 2 °C em TXT ou 1 °C em DB; acima de 8 °C.
- **Freezer −30 °C:** alerta abaixo de −45 °C ou acima de −15 °C.
- **Al:** sinal original do controlador. Alta e baixa temperatura são
  apresentadas mesmo com Al=0.
- **Porta:** o alarme de porta exige PA=1 e Al=1. PA=1 sozinho não gera esse alarme.

Os contadores representam **registros**, não episódios completos de alarme.
Um registro pode atender a mais de uma condição.

## Cuidados com os dados

O menu de três pontos oferece a ajuda **Como usar / Sobre**.

O aplicativo apenas lê o arquivo original. Aceita um TXT ou DB por vez, com até
30 MB e 100.000 registros. Não reúne automaticamente arquivos de uma pasta IHM;
abra cada arquivo separadamente. Linhas com data ou formato inválidos são
ignoradas com aviso. Valores ausentes aparecem sem informação.

Esta versão Android não emite relatórios PDF nem Excel.

## Conferência desta atualização

A abertura do aplicativo, a leitura pelo pendrive e a comparação dos dados da
versão anterior foram confirmadas no Galaxy Tab A11 com Android 16. As novas
abas e filtros foram conferidos no computador em telas de 390, 600 e 1100 pixels
de largura. O APK atualizado precisa ser conferido novamente no tablet.

A prévia no computador continua disponível em **abrir_previa.bat**.
As instruções de compilação estão em [ANDROID.md](ANDROID.md).
