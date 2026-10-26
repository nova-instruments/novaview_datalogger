import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: table
    property string tabKey: "data"
    property var pageInfo: ({rows: [], total: 0, page: 0, pages: 1, first: 0, last: 0})
    property bool filtersVisible: width >= 650
    signal recordSelected(var record)
    spacing: 8
    function apply() {
        backend.setFilters(tabKey, search.text, kinds[kindBox.currentIndex], minimum.text, maximum.text, order.currentIndex === 0)
    }
    function clearFields() {
        search.text = ""; minimum.text = ""; maximum.text = ""; kindBox.currentIndex = 0; order.currentIndex = 0
    }
    property var kinds: tabKey === "alarms" ? ["any", "high", "low", "door", "generic"] : ["all", "any", "high", "low", "door", "generic", "none"]
    property var titles: ["Registro", "Data e hora", "Principal °C", "Setpoint °C", "Porta", "Al", "Condição"]
    property var widths: [80, 180, 108, 108, 70, 60, 290]
    function text(value) { return value === null || value === undefined ? "—" : value.toString() }
    function temperature(value) { return value === null || value === undefined ? "—" : Number(value).toFixed(2).replace(".", ",") }
    RowLayout {
        Layout.fillWidth: true
        Label { text: pageInfo.total + (tabKey === "alarms" ? " registros com alerta" : " registros encontrados"); font.bold: true; color: "#123b58"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
        Button { text: table.filtersVisible ? "Ocultar filtros" : "Filtros"; implicitHeight: 46; onClicked: table.filtersVisible = !table.filtersVisible }
    }
    Flow {
        visible: table.filtersVisible
        Layout.fillWidth: true
        Layout.preferredHeight: implicitHeight
        spacing: 8
        TextField { id: search; objectName: table.tabKey + "Search"; width: Math.min(290, table.width); height: 48; placeholderText: "Buscar registro, data ou condição"; onAccepted: table.apply(); selectByMouse: true }
        ComboBox { id: kindBox; objectName: table.tabKey + "AlarmFilter"; width: Math.min(230, table.width); height: 48; model: table.tabKey === "alarms" ? ["Todos os alertas", "Alta temperatura", "Baixa temperatura", "Porta aberta", "Sem classificação"] : ["Todos os registros", "Qualquer alerta", "Alta temperatura", "Baixa temperatura", "Porta aberta", "Sem classificação", "Sem alarme"] }
        TextField { id: minimum; objectName: table.tabKey + "Minimum"; width: 130; height: 48; placeholderText: "Mínima °C"; inputMethodHints: Qt.ImhFormattedNumbersOnly; onAccepted: table.apply() }
        TextField { id: maximum; objectName: table.tabKey + "Maximum"; width: 130; height: 48; placeholderText: "Máxima °C"; inputMethodHints: Qt.ImhFormattedNumbersOnly; onAccepted: table.apply() }
        ComboBox { id: order; width: 190; height: 48; model: ["Mais recentes primeiro", "Mais antigos primeiro"] }
        Button { objectName: table.tabKey + "Apply"; text: "Aplicar"; width: 100; height: 48; onClicked: table.apply() }
        Button { text: "Limpar"; width: 90; height: 48; onClicked: { table.clearFields(); backend.resetFilters(table.tabKey) } }
    }
    Label { text: "Temperaturas inclusivas • Toque na linha para ver os detalhes • Deslize para os lados para ver todas as colunas"; color: "#537087"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    Flickable {
        id: horizontal
        objectName: table.tabKey + "Table"
        Layout.fillWidth: true; Layout.fillHeight: true
        Layout.minimumHeight: 130
        clip: true
        contentWidth: Math.max(width, 996)
        contentHeight: height
        flickableDirection: Flickable.HorizontalFlick
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
        ColumnLayout {
            width: horizontal.contentWidth; height: horizontal.height
            spacing: 0
            Rectangle {
                Layout.fillWidth: true; implicitHeight: 44; color: "#e7eff5"
                Row {
                    anchors.fill: parent
                    Repeater {
                        model: table.titles
                        Label { required property int index; required property string modelData; width: table.widths[index]; height: 44; text: modelData; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; color: "#123b58"; font.bold: true }
                    }
                }
            }
            ListView {
                id: records
                objectName: table.tabKey + "Rows"
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; model: table.pageInfo.rows
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                onModelChanged: positionViewAtBeginning()
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: records.width; height: 56
                    color: index%2 ? "#f5f8fb" : "white"
                    property var cells: [table.text(modelData.number), modelData.time, table.temperature(modelData.y), table.temperature(modelData.setpoint), table.text(modelData.door), table.text(modelData.alarm), modelData.kind]
                    Row {
                        anchors.fill: parent
                        Repeater {
                            model: parent.parent.cells
                            Label { required property int index; required property var modelData; width: table.widths[index]; height: 56; text: modelData; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; color: "#123b58"; elide: Text.ElideRight; textFormat: Text.PlainText; leftPadding: 4; rightPadding: 4 }
                        }
                    }
                    TapHandler { onTapped: table.recordSelected(parent.modelData) }
                }
                Label { anchors.centerIn: parent; visible: records.count === 0; text: "Nenhum registro neste filtro."; color: "#537087" }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Label { text: pageInfo.first + "–" + pageInfo.last + " de " + pageInfo.total; color: "#537087"; Layout.fillWidth: true }
        Button { objectName: table.tabKey + "Previous"; text: "‹"; Accessible.name: "Página anterior"; implicitWidth: 48; implicitHeight: 48; enabled: pageInfo.page > 0; onClicked: backend.setPage(table.tabKey, table.pageInfo.page - 1) }
        Label { text: (pageInfo.page + 1) + "/" + pageInfo.pages; color: "#123b58" }
        Button { objectName: table.tabKey + "Next"; text: "›"; Accessible.name: "Próxima página"; implicitWidth: 48; implicitHeight: 48; enabled: pageInfo.page + 1 < pageInfo.pages; onClicked: backend.setPage(table.tabKey, table.pageInfo.page + 1) }
    }
}
