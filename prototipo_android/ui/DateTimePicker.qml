import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: picker
    objectName: "periodPicker"
    modal: true
    width: Math.min(parent.width - 24, 470)
    anchors.centerIn: parent
    title: "Escolher data e hora"
    property var days: []
    property double minimum: 0
    property double maximum: 0
    property double value: 0
    signal chosen(double timestamp)
    function dayDate() {
        let day = days[dateBox.currentIndex]
        return day ? new Date(day.year, day.month - 1, day.day) : new Date(minimum)
    }
    property double dayStart: dayDate().getTime()
    property int minSeconds: Math.max(0, Math.round((minimum - dayStart) / 1000))
    property int maxSeconds: Math.min(86399, Math.round((maximum - dayStart) / 1000))
    function prepare(timestamp) {
        value = timestamp
        let date = new Date(timestamp)
        let index = days.findIndex(d => d.year === date.getFullYear() && d.month === date.getMonth()+1 && d.day === date.getDate())
        dateBox.currentIndex = Math.max(0, index)
        hours.value = date.getHours(); minutes.value = date.getMinutes(); seconds.value = date.getSeconds()
        open()
    }
    contentItem: ColumnLayout {
        spacing: 12
        Label { text: "Data com registros"; color: "#537087" }
        ComboBox { id: dateBox; objectName: "periodDay"; Layout.fillWidth: true; model: picker.days; textRole: "label"; implicitHeight: 48 }
        Label { text: "Hora • minuto • segundo"; color: "#537087" }
        RowLayout {
            Layout.fillWidth: true
            SpinBox { id: hours; objectName: "periodHour"; Layout.fillWidth: true; from: Math.floor(picker.minSeconds / 3600); to: Math.floor(picker.maxSeconds / 3600); editable: true; implicitHeight: 48 }
            SpinBox { id: minutes; Layout.fillWidth: true; from: hours.value === Math.floor(picker.minSeconds/3600) ? Math.floor(picker.minSeconds%3600/60) : 0; to: hours.value === Math.floor(picker.maxSeconds/3600) ? Math.floor(picker.maxSeconds%3600/60) : 59; editable: true; implicitHeight: 48 }
            SpinBox { id: seconds; Layout.fillWidth: true; from: hours.value*60+minutes.value === Math.floor(picker.minSeconds/60) ? picker.minSeconds%60 : 0; to: hours.value*60+minutes.value === Math.floor(picker.maxSeconds/60) ? picker.maxSeconds%60 : 59; editable: true; implicitHeight: 48 }
        }
        Label { text: "A seleção respeita o início e o fim do datalogger."; wrapMode: Text.WordWrap; Layout.fillWidth: true; color: "#537087" }
        RowLayout {
            Item { Layout.fillWidth: true }
            Button { text: "Cancelar"; implicitHeight: 48; onClicked: picker.reject() }
            Button { text: "Selecionar"; implicitHeight: 48; onClicked: { picker.chosen(picker.dayStart + (hours.value*3600 + minutes.value*60 + seconds.value)*1000); picker.accept() } }
        }
    }
}
