# novaview_datalogger_v1

O novaview_datalogger_v1 permite consultar os registros de temperatura de equipamentos NovaIOT, acompanhar suas variações em um gráfico, verificar alarmes e gerar relatórios. O programa funciona no computador, sem precisar abrir um navegador.

## Como começar

1. Após a extração de dados da máquina conecte o pendrive Nova Instruments e abra novaview_datalogger_v1.exe.
2. Clique em **Abrir arquivo** e escolha os registros do equipamento. O programa aceita arquivos **TXT** e **DB**. Você também pode arrastar um arquivo para a janela.
3. Para consultar registros de uma IHM, clique em **Abrir pasta IHM** e selecione a pasta dos registros ou a pasta que contém **DataLogFile**. O programa reúne os arquivos encontrados para apresentar os dados juntos.
4. Deixe **Tipo de equipamento** em **Automático**: ao abrir os registros, o programa identifica **Câmara Fria** ou **Freezer −30 °C** pelas temperaturas. Confira o resultado e os limites de alerta exibidos ao lado. Se necessário, escolha o tipo manualmente.
5. Use as abas **Painel**, **Dados** e **Alarmes** para fazer sua análise.

O programa abre com a janela maximizada. Os arquivos originais são apenas consultados: suas informações não são alteradas.

## Painel: acompanhe as temperaturas

O Painel mostra o número de série do equipamento, o início e o fim dos registros e um gráfico das medições. Ao abrir um arquivo, o gráfico apresenta inicialmente as últimas 24 horas disponíveis nos registros.

- Clique em **Mostrar filtros e indicadores** para escolher outro período e consultar a temperatura média, a maior, a menor e o setpoint médio, quando disponível. O setpoint é a temperatura de referência registrada pelo equipamento.
- Preencha **De (data e hora)** e **Até (data e hora)** e clique em **Confirmar período**. Só é possível escolher datas e horários dentro do intervalo dos registros.
- Marque as medições que deseja ver no gráfico.
- Use a **roda do mouse** para aproximar ou afastar o gráfico.
- **Clique e arraste** para se mover pelo gráfico.
- **Clique em um ponto** para consultar os dados daquele registro na tabela abaixo.
- Clique em **Restaurar gráfico** para voltar à visão completa do período selecionado.

## Dados: encontre registros específicos

Nesta aba, você pode consultar os registros em uma tabela e conferir o número de série do equipamento.

- Escolha os últimos **1, 7, 15 ou 30 dias**, ou o período **Completo**. Esses períodos são contados a partir do último registro disponível.
- Use a busca para encontrar um texto ou valor nas colunas da tabela.
- Filtre por **tipo de alarme** ou informe uma temperatura **mínima e máxima**. Os valores mínimo e máximo também entram na busca.
- Combine os filtros e clique em **Aplicar filtros**.
- Use **Limpar filtros** para retirar a busca e os filtros de alarme e temperatura.
- Clique no título de uma coluna para ordenar os registros.

As temperaturas podem ser digitadas com vírgula ou ponto, como **2,5** ou **2.5**. Deixe um dos limites em branco quando quiser pesquisar sem limite mínimo ou máximo. Campos que não existem no arquivo do equipamento podem não aparecer na tabela.

## Alarmes: entenda as condições registradas

A aba Alarmes mostra o último evento, o histórico e os totais de registros com alta temperatura, baixa temperatura e porta aberta. Ela considera todo o arquivo importado, independentemente do período escolhido no Painel ou na aba Dados.

**Temperatura fora da faixa e confirmação do controlador são informações diferentes:**

- **Câmara Fria:** alta temperatura acima de **8 °C**; baixa temperatura abaixo de **2 °C** em arquivos TXT e pastas IHM, ou abaixo de **1 °C** em um arquivo DB aberto individualmente.
- **Freezer −30 °C:** alta temperatura acima de **−15 °C** e baixa temperatura abaixo de **−45 °C**, em todos os formatos de arquivo. Uma leitura de **−30 °C** está dentro dessa faixa.
- Os valores exatamente nesses limites não geram alerta de temperatura.
- Os alertas de temperatura aparecem mesmo quando o controlador ainda não confirmou o alarme. Isso permite identificar quando a condição começou.

A coluna **alarme** mostra o estado registrado pelo controlador: **0** significa sem confirmação de alarme e **1** significa alarme ativo. Nos arquivos TXT, essa informação vem do campo **Al**. Um campo vazio significa que a informação não está disponível.

O tipo **porta aberta** aparece quando há indicação de porta aberta e alarme ativo. Se também houver temperatura fora da faixa, o tipo exibido prioriza a porta; o registro continua incluído no contador e no filtro de alta ou baixa temperatura. Quando há alarme ativo sem uma dessas condições, aparece **Alarme ativo (sem classificação)**.

Os limites acima são usados pelo programa e podem ser diferentes dos limites configurados no equipamento. O tipo apresentado indica as condições observadas; o campo Al, sozinho, não informa a causa exata do alarme do controlador. Em formatos antigos de TXT ou pasta IHM sem campo de alarme, o programa calcula esse estado a partir da porta e da temperatura.

No modo **Automático**, o programa considera a temperatura central do arquivo inteiro, reduzindo a influência de picos isolados: até **−10 °C**, identifica **Freezer −30 °C**; acima disso, **Câmara Fria**. Esse valor serve apenas para identificar o tipo, não é um limite de alarme. A identificação é uma estimativa: se o arquivo contiver principalmente temperaturas fora da operação normal, confira o resultado e corrija a seleção manualmente. Sem temperaturas válidas, o programa informa que não foi possível identificar. A escolha vale para as três abas e para os relatórios, e pode ser alterada sem abrir o arquivo novamente.

Os contadores representam **quantidades de registros**, não ocorrências separadas. Uma condição que dure várias leituras será contada em cada uma delas, e um registro pode aparecer em mais de um contador.

## Salvar os resultados

Na aba Dados, estão disponíveis duas opções:

- **Exportar Excel:** salva os registros que aparecem após aplicar os filtros, mantendo a ordem escolhida na tabela.
- **Gerar PDF:** cria um relatório com resumo, gráfico, últimos alarmes e os registros do período escolhido. A busca por texto e os filtros de alarme e temperatura não restringem esse relatório.

Escolha o nome e a pasta onde deseja salvar o arquivo. Os relatórios já gerados continuam disponíveis para abrir, imprimir ou compartilhar.

## Dúvidas comuns

**O número de série aparece como “Não informado”.**
O programa não encontrou essa identificação no arquivo. Confira o arquivo e seu nome.

**Não apareceram registros depois de filtrar.**
Confira o período escolhido e use **Limpar filtros**. Verifique se a faixa de temperatura informada corresponde aos dados que deseja consultar.

**Uma temperatura gerou alerta, mas a coluna alarme está em 0.**
Isso é esperado: a temperatura já está fora dos limites usados pelo programa, mas o controlador não registrou alarme ativo naquele momento.

**O arquivo recebeu novas leituras enquanto estava aberto.**
Abra o arquivo novamente para carregar os registros atualizados.

**O programa está carregando ou salvando um relatório.**
Aguarde a conclusão. Alguns botões ficam temporariamente indisponíveis durante essas operações.

## Instala??o para desenvolvimento (Windows)

Use Python 3.13 de 64 bits. No PowerShell, na pasta do projeto:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_app.py
```

Para executar os testes do aplicativo Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Gerar o execut?vel Windows

Execute `build_windows.bat`. O script instala as depend?ncias de compila??o e gera `dist/novaview_datalogger_v1.exe`.

O execut?vel pronto para uso est? dispon?vel nas [vers?es do GitHub](https://github.com/nova-instruments/novaview_datalogger/releases). Os arquivos de compila??o, ambientes virtuais e dados locais n?o fazem parte do c?digo versionado.

## Prot?tipo Android

O desenvolvimento Android fica em `prototipo_android/`, com instru??es e depend?ncias pr?prias no [README do prot?tipo](prototipo_android/README.md). Os testes acima validam a vers?o Windows; a valida??o do Android ? independente.
