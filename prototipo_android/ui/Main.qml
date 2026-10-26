import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
    id: window
    objectName: "prototypeWindow"
    visible: true
    width: 1100; height: 860
    minimumWidth: 360; minimumHeight: 600
    title: "NovaView Datalogger"
    color: "#f2f6fa"
    font.family: Qt.platform.os === "windows" ? "Segoe UI" : "sans-serif"
    font.pixelSize: 14
    palette.button: "white"
    palette.buttonText: "#123b58"
    palette.highlight: "#07998f"
    palette.highlightedText: "white"
    property var info: backend.summary
    property var selectedRecord: ({})
    property bool periodExpanded: false
    property bool choosingStart: true
    property double draftStart: info.start
    property double draftEnd: info.end
    function valueText(value) { return value === null || value === undefined ? "Não informado" : value.toString() }
    function temperatureText(value) { return value === null || value === undefined ? "—" : Number(value).toFixed(2).replace(".", ",") + " °C" }
    function dateText(value) { return Qt.formatDateTime(new Date(value), "dd/MM/yyyy HH:mm:ss") }
    function chooseDate(start) {
        choosingStart = start
        periodPicker.prepare(start ? draftStart : draftEnd)
    }
    function showRecord(record) { selectedRecord = record; recordDialog.open() }
    component NavigationTab: TabButton {
        implicitHeight: 48
        background: Rectangle {
            color: parent.checked ? "white" : "#e7eff5"
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 3; color: "#07998f"; visible: parent.parent.checked }
        }
        contentItem: Label { text: parent.text; font.bold: parent.checked; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; color: "#123b58" }
    }
    Connections {
        target: backend
        function onChanged() {
            window.selectedRecord = ({})
            window.draftStart = window.info.start; window.draftEnd = window.info.end
            equipmentSelector.currentIndex = ["auto", "cold_chamber", "freezer"].indexOf(backend.profileValue)
        }
        function onError(message) { errorLabel.text = message; errorDialog.open() }
        function onFileChanged() { dataTable.clearFields(); alarmTable.clearFields() }
    }
    FileDialog {
        id: fileDialog
        title: "Abrir registros do datalogger"
        nameFilters: ["Arquivos do equipamento (*.txt *.TXT *.db *.DB *.sqlite *.sqlite3)", "Todos os arquivos (*)"]
        onAccepted: backend.startOpenFile(selectedFile)
    }
    DateTimePicker {
        id: periodPicker
        parent: Overlay.overlay
        days: backend.availableDays
        minimum: window.info.loaded ? window.info.fullStart : 0
        maximum: window.info.loaded ? window.info.fullEnd : 0
        onChosen: (timestamp) => { if (window.choosingStart) window.draftStart = timestamp; else window.draftEnd = timestamp }
    }
    Dialog {
        id: errorDialog
        parent: Overlay.overlay
        title: "Confira a seleção"
        modal: true; anchors.centerIn: parent
        width: Math.min(window.width - 32, 480)
        standardButtons: Dialog.Ok
        contentItem: Label { id: errorLabel; wrapMode: Text.WordWrap; textFormat: Text.PlainText }
    }
    Dialog {
        id: recordDialog
        parent: Overlay.overlay
        objectName: "recordDialog"
        title: "Detalhes do registro"
        modal: true; anchors.centerIn: parent
        width: Math.min(window.width - 24, 490)
        standardButtons: Dialog.Ok
        contentItem: ColumnLayout {
            spacing: 10
            Label { text: window.selectedRecord.time || ""; font.bold: true; color: "#123b58"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Label { text: "Registro: " + window.valueText(window.selectedRecord.number); Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.PlainText }
            Label { text: "Principal: " + window.temperatureText(window.selectedRecord.y) + "\nSetpoint: " + window.temperatureText(window.selectedRecord.setpoint) + "\nDegelo: " + window.temperatureText(window.selectedRecord.defrost) + "\nTomada: " + window.temperatureText(window.selectedRecord.outlet) + "\nBateria: " + window.valueText(window.selectedRecord.battery); lineHeight: 1.5; Layout.fillWidth: true }
            Label { text: "Porta (PA): " + window.valueText(window.selectedRecord.door) + "\nAl do controlador: " + window.valueText(window.selectedRecord.alarm); lineHeight: 1.5; Layout.fillWidth: true }
            Label { text: window.selectedRecord.kind || ""; color: "#996a25"; font.bold: true; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Label { text: "Alta e baixa temperatura independem de Al. O alarme de porta exige PA=1 e Al=1."; color: "#537087"; Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: 12 }
        }
    }
    Dialog {
        id: aboutDialog
        parent: Overlay.overlay
        title: "NovaView Datalogger • Android 0.2.1"
        modal: true; anchors.centerIn: parent
        width: Math.min(window.width - 24, 500)
        height: Math.min(window.height - 40, 650)
        standardButtons: Dialog.Ok
        contentItem: ScrollView {
            id: aboutScroll
            clip: true; contentWidth: availableWidth
            Label {
            width: aboutScroll.availableWidth
            text: "Abra um arquivo TXT ou DB do equipamento, salvo no tablet ou no pendrive Nova Instruments.\n\nPainel: gráfico e indicadores.\nDados: todos os registros.\nAlarmes: condições de temperatura e alarmes do controlador.\n\nO período é compartilhado entre as abas. Nas tabelas, combine busca, tipo de alarme e faixa de temperatura. Toque na linha para ver os detalhes.\n\nFreezer: mínima −45 °C e máxima −15 °C.\nCâmara Fria: mínima 2 °C em TXT ou 1 °C em DB; máxima 8 °C.\n\nLeitura de até 30 MB e 100.000 registros por arquivo. Os arquivos originais não são alterados. O uso não precisa de internet."
            wrapMode: Text.WordWrap; textFormat: Text.PlainText; color: "#123b58"
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: window.width < 600 ? 10 : 18
        spacing: 8
        Rectangle {
            Layout.fillWidth: true; implicitHeight: window.width < 600 ? 76 : 90
            radius: 14; color: "white"; border.color: "#dce6ed"
            RowLayout {
                anchors.fill: parent; anchors.margins: 10; spacing: 10
                Image { source: "../assets/logo_header.png"; Layout.fillWidth: true; Layout.maximumWidth: 380; Layout.preferredHeight: parent.height; fillMode: Image.PreserveAspectFit; horizontalAlignment: Image.AlignLeft }
                Item { Layout.fillWidth: true }
                Button { objectName: "openFileButton"; text: "Abrir arquivo"; implicitHeight: 48; implicitWidth: window.width < 600 ? 120 : 155; enabled: !backend.busy; onClicked: fileDialog.open(); palette.button: "#07998f"; palette.buttonText: "white" }
                ToolButton { implicitWidth: 40; implicitHeight: 48; enabled: !backend.busy; Accessible.name: "Opções"; onClicked: optionsMenu.open()
                    contentItem: Item { Column { anchors.centerIn: parent; spacing: 4; Repeater { model: 3; Rectangle { width: 4; height: 4; radius: 2; color: "#123b58" } } } }
                    Menu {
                        id: optionsMenu
                        x: parent.width - width; y: parent.height
                        MenuItem { text: "Como usar / Sobre"; onTriggered: aboutDialog.open() }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true; spacing: 2
                Label { text: info.loaded ? "Número de série: " + info.serial : "Seus registros, onde você estiver"; font.bold: true; font.pixelSize: window.width < 600 ? 16 : 20; color: "#123b58"; Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.PlainText }
                Label { text: info.loaded ? info.source + " • " + info.count + " registros" : "Abra um arquivo do equipamento salvo no tablet ou no pendrive"; color: "#537087"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.PlainText }
            }
        }
        Rectangle {
            visible: info.loaded
            Layout.fillWidth: true
            implicitHeight: periodColumn.implicitHeight + 20
            color: "white"; radius: 12; border.color: "#dce6ed"
            ColumnLayout {
                id: periodColumn
                anchors { fill: parent; margins: 10 }
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Período • " + (info.periodCount || 0) + " registros"; color: "#123b58"; font.bold: true; Layout.fillWidth: true }
                    Button { objectName: "togglePeriodButton"; text: window.periodExpanded ? "Ocultar" : "Alterar"; implicitHeight: 44; onClicked: window.periodExpanded = !window.periodExpanded }
                }
                Label { visible: window.periodExpanded; text: info.loaded ? "Início do datalogger: " + info.startLabel + "\nFim do datalogger: " + info.endLabel : ""; color: "#537087"; Layout.fillWidth: true; wrapMode: Text.WordWrap; lineHeight: 1.4 }
                Flow {
                    visible: window.periodExpanded
                    Layout.fillWidth: true; Layout.preferredHeight: implicitHeight; spacing: 10
                    Column { spacing: 4; width: Math.min(235, periodColumn.width)
                        Label { text: "De (data e hora)"; color: "#537087" }
                        Button { objectName: "periodStartButton"; width: parent.width; height: 48; text: window.dateText(window.draftStart); onClicked: window.chooseDate(true) }
                    }
                    Column { spacing: 4; width: Math.min(235, periodColumn.width)
                        Label { text: "Até (data e hora)"; color: "#537087" }
                        Button { objectName: "periodEndButton"; width: parent.width; height: 48; text: window.dateText(window.draftEnd); onClicked: window.chooseDate(false) }
                    }
                    Column { spacing: 4
                        Label { text: " "; visible: window.width > 600 }
                        Row { spacing: 8
                            Button { objectName: "applyPeriodButton"; text: "Aplicar período"; height: 48; onClicked: backend.setPeriod(window.draftStart, window.draftEnd) }
                            Button { text: "Completo"; height: 48; onClicked: backend.resetPeriod() }
                        }
                    }
                }
                Label { visible: !window.periodExpanded; text: info.loaded ? info.periodStartLabel + "  →  " + info.periodEndLabel : ""; color: "#537087"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            }
        }
        TabBar {
            id: tabs; objectName: "mainTabs"
            Layout.fillWidth: true
            NavigationTab { text: "Painel" }
            NavigationTab { objectName: "dataTab"; text: "Dados" }
            NavigationTab { objectName: "alarmsTab"; text: "Alarmes" }
        }
        StackLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            currentIndex: tabs.currentIndex
            ScrollView {
                id: panel
                objectName: "panelScroll"
                clip: true; contentWidth: availableWidth
                ColumnLayout {
                    width: panel.availableWidth; spacing: 10
                    Label { visible: info.notice !== ""; text: info.notice; color: "#a16d24"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    RowLayout {
                        visible: info.loaded; Layout.fillWidth: true
                        ComboBox { id: equipmentSelector; objectName: "equipmentSelector"; implicitWidth: 160; implicitHeight: 48; model: ["Automático", "Câmara Fria", "Freezer −30 °C"]; onActivated: backend.setProfile(["auto", "cold_chamber", "freezer"][currentIndex]) }
                        Label { text: info.equipment + "\n" + info.limits; color: "#537087"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    }
                    GridLayout {
                        visible: info.loaded; Layout.fillWidth: true
                        columns: window.width < 650 ? 2 : 4
                        columnSpacing: 8; rowSpacing: 8
                        Repeater {
                            model: info.loaded ? [{label: "Temperatura média", value: info.average}, {label: "Maior temperatura", value: info.maximum}, {label: "Menor temperatura", value: info.minimum}, {label: "Setpoint médio", value: info.setpointAverage}] : []
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true; implicitHeight: 82; radius: 12; color: "white"; border.color: "#dce6ed"
                                Column { anchors { fill: parent; margins: 12 }
spacing: 6
                                    Label { text: modelData.label; font.pixelSize: 12; color: "#537087" }
                                    Label { text: window.temperatureText(modelData.value); font.bold: true; font.pixelSize: 23; color: "#07998f" }
                                }
                            }
                        }
                    }
                    RowLayout {
                        visible: info.loaded; Layout.fillWidth: true
                        CheckBox { text: "Principal"; checked: true; onToggled: chart.showPrincipal = checked }
                        CheckBox { visible: info.hasSetpoint || false; text: "Setpoint"; checked: true; onToggled: chart.showSetpoint = checked }
                        CheckBox { text: "Porta"; checked: false; onToggled: chart.showDoor = checked }
                        Item { Layout.fillWidth: true }
                        Button { objectName: "resetChartButton"; text: "Restaurar"; implicitHeight: 46; onClicked: chart.reset() }
                    }
                    TemperatureChart {
                        id: chart; Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(window.width < 600 ? 320 : 370, panel.height - (window.info.loaded ? 270 : 0))
                        info: window.info
                        onRecordSelected: (record) => window.showRecord(record)
                    }
                    Label { text: "Toque: dados • Arraste: mover • Dois dedos ou roda do mouse: zoom"; color: "#537087"; Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: 12 }
                    GridLayout {
                        visible: info.loaded; Layout.fillWidth: true
                        columns: window.width < 650 ? 2 : 4; columnSpacing: 8; rowSpacing: 8
                        Repeater {
                            model: info.loaded ? [{label: "Registros com alerta", value: info.counts.total}, {label: "Alta temperatura", value: info.counts.high}, {label: "Baixa temperatura", value: info.counts.low}, {label: "Porta aberta", value: info.counts.door}] : []
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true; implicitHeight: 72; color: "white"; radius: 12; border.color: "#dce6ed"
                                Column { anchors { fill: parent; margins: 10 }
spacing: 4
                                    Label { text: modelData.label; color: "#537087"; font.pixelSize: 12 }
                                    Label { text: modelData.value; color: "#07998f"; font.bold: true; font.pixelSize: 24 }
                                }
                            }
                        }
                    }
                    Label { visible: info.loaded; text: "Contadores representam registros no período. Alta/baixa independem de Al; porta exige PA=1 e Al=1. Consulte todos os alertas na aba Alarmes."; wrapMode: Text.WordWrap; Layout.fillWidth: true; color: "#537087"; font.pixelSize: 12; Layout.bottomMargin: 12 }
                }
            }
            RecordTable { id: dataTable; tabKey: "data"; pageInfo: backend.dataPage; onRecordSelected: (record) => window.showRecord(record) }
            RecordTable { id: alarmTable; tabKey: "alarms"; pageInfo: backend.alarmPage; onRecordSelected: (record) => window.showRecord(record) }
        }
    }
    Popup {
        id: loading
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true; closePolicy: Popup.NoAutoClose
        visible: backend.busy
        width: Math.min(window.width - 32, 340)
        contentItem: RowLayout {
            spacing: 12
            BusyIndicator { running: backend.busy }
            Label { text: "Lendo registros…"; color: "#123b58" }
        }
    }
}
