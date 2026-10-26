# Compilar e validar o Android

Esta etapa é exclusiva da versão Android isolada. Não use os scripts da pasta
principal. A interface usa PySide6 com Qt Quick e um gráfico Canvas; o leitor TXT/DB
usa a biblioteca padrão do Python. Não depende de pandas, NumPy ou PyQtGraph.

## Estado desta entrega

APK 0.2.1 disponível em `dist/NovaView-Android-ARM64.apk`, com
assinatura de desenvolvimento e arquitetura ARM64, sem dados de demonstração.
Foram conferidas 633 bibliotecas nativas, com alinhamento de segmentos de 16 KB
e sem conflito entre páginas RELRO e dados graváveis. A versão anterior teve
instalação, leitura do pendrive e comparação com Windows confirmadas pelo usuário.
As novas abas, filtros e leitura DB precisam de nova conferência no tablet.
O Ubuntu 22.04 via WSL recebeu Java 17 e os pré-requisitos
de compilação. Python, SDK, NDK, pacotes Android e a cópia de trabalho ficam em
`/home/nova/novaview-android-prototype-build`, separados do aplicativo Windows.
O ambiente Python e o executável Windows validados foram preservados.

O script `preparar_compilacao.py` prepara essa pasta de trabalho e chama o
empacotador oficial. No Ubuntu, execute:

```bash
python3 /caminho/prototipo_android/preparar_compilacao.py
```

O caminho `/caminho` é um exemplo; use o caminho real desta pasta. O resultado é
copiado para `prototipo_android/dist/`. Os detalhes desta execução estão em
`qa/compilacao_android.log`. Para retomar uma compilação já preparada e manter o
cache nativo, acrescente `--resume`. A ferramenta do Qt recria o cache ao iniciar
uma compilação completa; o modo de retomada chama o Buildozer já configurado.

O empacotador recebeu ajustes para permitir
rotação da tela. O identificador interno não contém espaços, pois ele também
é usado em caminhos de compilação. O nome exibido no Android é **NovaView Datalogger**.

A atualização inclui Painel, Dados e Alarmes, período comum às abas, consultas
paginadas de 50 linhas, filtros combinados, leitura assíncrona e recursos da marca.
Não há emissão de relatórios. Arquivos DB são copiados temporariamente para o
armazenamento privado e lidos em modo somente leitura. Não há importação de
pastas ou união automática de bancos IHM nesta versão.

Para atualizar somente fontes e recursos em um ambiente já preparado:

```bash
/home/nova/novaview-android-prototype-build/venv/bin/python \
  /caminho/prototipo_android/qa/finalize_android_package.py
```

`qa/update_android_app.py` preserva os arquivos do bootstrap e atualiza a versão
dos dados internos pelo hash das fontes. Isso força a extração dos novos arquivos
ao atualizar o aplicativo. O versionCode é 10283, superior ao APK anterior, e o
identificador e a chave de teste continuam os mesmos para permitir atualização.
Os arquivos empacotados e as verificações estão em `qa/apk_verificacao_final.json`.

Os testes podem ser executados com `python -m unittest discover -s prototipo_android/tests -v`.
As imagens de conferência das três abas e do seletor de período estão em `qa/`.

O wheel oficial Shiboken 6.12.0 forneceu um módulo `Shiboken.abi3.so` com alinhamento
de 4 KB. Esse módulo foi regenerado e recompilado a partir do código oficial da
mesma versão, com o NDK r28c e opções de link para páginas de 16 KB. Os demais
arquivos do pacote Python foram preservados; o registro de integridade do módulo
foi atualizado. A assinatura foi refeita pelo Gradle e verificada depois.
Essa etapa é reproduzida por `qa/rebuild_shiboken_16kb.py` e
`qa/finalize_android_package.py`, chamadas pela preparação completa.

O relatório está em `qa/apk_verificacao_final.json`. A origem do código recompilado,
a versão e os parâmetros estão registrados nesse relatório. Isso é validação
estática do pacote e não substitui executar o aplicativo no Galaxy Tab A11.

## Tablet informado: Galaxy Tab A11 com Android 16

A prévia foi aprovada no Windows pelo usuário. O próximo alvo de teste é o
Galaxy Tab A11 com Android 16 (API 36). Android 16 está entre as plataformas
[suportadas pelo Qt 6.12](https://doc.qt.io/qt-6/supported-platforms.html).
O alvo inicial de compilação é **ARM64 (aarch64/arm64-v8a)**, padrão do script.
O sistema Android 16 do tablet não exige que o SDK de compilação seja API 36:
use o conjunto SDK/NDK exigido pelo empacotador Qt 6.12.

O script confere se os pacotes fornecidos são Android ARM64 e da versão 6.12.0.
Pacotes Windows, Linux e Android x86_64 são recusados na configuração padrão.
Para compilar especificamente para um emulador x86_64, informe `--arch x86_64`.
Essa verificação não equivale a um APK já compilado ou validado no aparelho.

Após a compilação, copie o APK para o tablet e abra-o pelo aplicativo de arquivos.
Se o Android solicitar, permita a instalação desse arquivo pela origem usada.
Teste primeiro um TXT no armazenamento interno;
por último, experimente o pendrive e os gestos.

## Preparação em Linux ou macOS

Copie somente esta pasta para um diretório de trabalho próprio. No WSL, prefira
um diretório Linux para compilar, mantendo os arquivos originais intactos.
Crie o ambiente de compilação **fora** da pasta do protótipo:

```bash
python3 -m venv ../novaview-android-venv
source ../novaview-android-venv/bin/activate
python -m pip install -r requirements.txt
```

Instale Java 17 ou mais recente e prepare o Android SDK/NDK conforme a
[documentação oficial do Qt](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-android-deploy.html).
Na documentação consultada para Qt 6.12, são indicados SDK Android 35, build-tools
35.0.0 e NDK r28c (28.2.13676358). Siga as versões exigidas pelo Qt usado na compilação.

Baixe os pacotes Android de **PySide6 e shiboken6 da mesma versão e arquitetura**
na [página oficial de downloads](https://download.qt.io/official_releases/QtForPython/).
Para tablets ARM64, use aarch64/arm64-v8a. Para emulador x86_64, use os pacotes x86_64.
Os pacotes do Windows não servem para Android. Os pacotes Android também precisam
ser compatíveis com a versão Python usada pelo empacotador oficial.

## Gerar APK de teste

Com o ambiente ativado e estando nesta pasta:

```bash
python gerar_apk.py \
  --arch aarch64 \
  --wheel-pyside /caminho/PySide6-android.whl \
  --wheel-shiboken /caminho/shiboken6-android.whl \
  --sdk-path /caminho/android-sdk \
  --ndk-path /caminho/android-sdk/ndk/28.2.13676358
```

Os nomes acima são exemplos: informe os arquivos reais baixados. O script chama
`pyside6-android-deploy`, que prepara as dependências em seu ambiente de compilação.
O projeto lista apenas seus próprios arquivos em `pyproject.toml`. O empacotador
gera `pysidedeploy.spec`; mantenha o modo `debug` na seção `buildozer` para APK de teste.
Depois da primeira geração, reutilize essa configuração com
`pyside6-android-deploy --config-file pysidedeploy.spec`.

O comando pode baixar dependências e precisa de internet durante a compilação.
O uso normal do protótipo não faz solicitações de rede. Licenças do SDK e de
outros componentes devem ser conferidas durante a preparação das ferramentas.

## Conferência no tablet

O retorno do seletor nativo também precisava de correção: o bootstrap Qt de
python-for-android interceptava `onActivityResult` sem chamar a implementação
de `QtActivity`. A finalização agora encaminha o resultado ao Qt antes dos
listeners opcionais e não chama `onResume` manualmente. O método é executado
em uma verificação Java com seleção, cancelamento e solicitações repetidas;
o comportamento com o seletor real ainda precisa de confirmação no tablet.

A primeira instalação apresentou “Could not extract”. O pacote interno estava
em PAX, mas o leitor jtar do bootstrap interpreta USTAR. A finalização agora
grava USTAR e verifica a extração completa dos dois arquivos internos usando
as próprias classes Java do bootstrap, antes de gerar o APK. Essa conferência
não substitui a abertura no aparelho real. Desinstale a versão anterior para
remover a extração incompleta antes de repetir o teste.

1. Instale o APK atualizado e abra um arquivo real do equipamento.
2. Confira Câmara Fria e Freezer, inclusive alertas com Al=0.
3. Experimente toque, movimento e zoom com dois dedos no gráfico.
4. Abra o TXT pelo seletor Android, primeiro do armazenamento interno e depois
   de um pendrive reconhecido pelo tablet. O programa usa QFile para ler a URL
   concedida pelo seletor, sem presumir um caminho fixo para o pendrive.
5. Teste com o tablet em pé e deitado, e com um arquivo maior.
6. Verifique se o arquivo original permaneceu intacto.

O funcionamento com URLs `content://`, o acesso ao pendrive e os gestos precisam
ser confirmados no aparelho escolhido. Não foram solicitadas permissões amplas
de armazenamento para contornar o seletor Android.

Referências: [Qt Quick FileDialog](https://doc.qt.io/qt-6/qml-qtquick-dialogs-filedialog.html),
[QFile](https://doc.qt.io/qt-6/qfile.html),
[PinchHandler](https://doc.qt.io/qt-6/qml-qtquick-pinchhandler.html).
