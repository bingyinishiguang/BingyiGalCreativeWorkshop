import QtQuick
import QtQuick.Controls

//冰翼取用精灵：桌宠 + 立绘总览的主窗口。
Window {
    id: root
    width: pet.sizeTier === "S" ? 160 : (pet.sizeTier === "L" ? 320 : 240)
    height: pet.sizeTier === "S" ? 230 : (pet.sizeTier === "L" ? 460 : 345)
    //最小尺寸需容纳切换按钮与状态条。
    minimumWidth: 160
    minimumHeight: 230
    //桌宠可见性由总览与拖放状态统一推导，避免多处命令切换不同步。
    visible: !galleryWindow.visible && !galleryWindow.dragging
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    title: "冰翼取用精灵"

    property bool moveMode: false
    readonly property bool controlsVisible: windowHover.hovered || moveMode || galleryWindow.visible
    readonly property color panelColor: "#d914375e"
    readonly property color panelHover: "#ee246fae"
    readonly property color iceBlue: "#8ad9ff"

    Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

    //位置变动后防抖保存，隐藏或最小化时跳过，避免记录系统占位坐标。
   Timer {
        id: geometrySaver
        interval: 500
        onTriggered: {
            if (root.visibility !== Window.Minimized && root.visibility !== Window.Hidden) {
                pet.saveGeometry(root.x, root.y, root.width, root.height, pet.sizeTier)
            }
        }
    }
    onXChanged: geometrySaver.restart()
    onYChanged: geometrySaver.restart()
    onClosing: pet.saveGeometry(root.x, root.y, root.width, root.height, pet.sizeTier)

    //托盘菜单的「显示桌宠 / 隐藏桌宠」文字与档位勾选要跟着实际状态走。
    onVisibleChanged: pet.syncTray()
    onVisibilityChanged: pet.syncTray()

    Component.onCompleted: {
        //告诉 Python 当前屏幕可用区域：托盘"把当前位置设为默认"要靠它判断是否放得下。
        pet.setScreenArea()
        pet.syncTray()
    }

    GalleryWindow {
        id: galleryWindow
        objectName: "galleryWindow"
        petWindow: root
    }

    Shortcut {
        sequence: "Esc"
        onActivated: root.moveMode = false
    }

    HoverHandler {
        id: windowHover
        acceptedDevices: PointerDevice.Mouse
    }

    //拖放期间直接隐藏窗口，结束后恢复。
    Item {
        id: petContent
        anchors.fill: parent
        scale: 1
        opacity: 1

        //加载与空图库分别显示，避免数据未就绪时闪现空态。
        Rectangle {
            id: loadingCard
            objectName: "loadingCard"
            anchors.centerIn: parent
            width: Math.min(parent.width - 16, 200)
            height: 118
            radius: 18
            visible: !pet.ready
            color: "#e6e6f4ff"
            border.width: 1
            border.color: root.iceBlue

            BusyIndicator {
                id: loadingSpinner
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 8
                width: 34
                height: 34
                running: loadingCard.visible
            }
            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: loadingSpinner.bottom
                anchors.topMargin: 6
                anchors.leftMargin: 11
                anchors.rightMargin: 11
                text: "正在整理立绘…"
                color: "#2e6b9e"
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
            }
        }

        //占位卡片只绑定稳定的空库状态，切换立绘时不会闪现。
       Rectangle {
            id: emptyCard
            objectName: "emptyCard"
            anchors.centerIn: parent
            width: Math.min(parent.width - 16, 200)
            height: 156
            radius: 18
            visible: pet.ready && pet.isEmpty
            color: "#e6e6f4ff"
            border.width: 1
            border.color: root.iceBlue

            Image {
                anchors.top: parent.top
                anchors.topMargin: 13
                anchors.horizontalCenter: parent.horizontalCenter
                width: 50
                height: 50
                //空图库显示透明雪狐图标。

                source: "mascot-icefox.png"
                fillMode: Image.PreserveAspectCrop
                smooth: true
            }
            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 13
                anchors.leftMargin: 11
                anchors.rightMargin: 11
                text: "立绘库是空的\n请先到冰翼Gal创作工坊保存立绘"
                color: "#2e6b9e"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
            }
        }

        //人物立绘本体：显示层只渲染「已解码完成」的图，换源瞬间保留上一张，不闪空。
        Image {
            id: spriteImage
            anchors.fill: parent
            anchors.margins: 6
            property url readySource
            source: readySource
            fillMode: Image.PreserveAspectFit
            cache: true
            //按显示尺寸解码，避免切换立绘时反复读取全分辨率图片。
           sourceSize: Qt.size(360, 540)
            smooth: true
            mipmap: true
            opacity: root.moveMode ? 0.62 : 1
            scale: root.moveMode ? 0.97 : 1
            Behavior on opacity { NumberAnimation { duration: 140 } }
            Behavior on scale { NumberAnimation { duration: 140 } }
        }

        //预载层：后台异步解码 pet.imageUrl，就绪后交给显示层；空态时同步清空显示层。
        Image {
            id: spritePreload
            anchors.fill: parent
            anchors.margins: 6
            visible: false
            source: pet.imageUrl
            asynchronous: true
            cache: true
            sourceSize: Qt.size(360, 540)
            onStatusChanged: {
                if (status === Image.Ready || status === Image.Null) {
                    spriteImage.readySource = source
                }
            }
        }

        //拖出 PNG 手势：按住人物移动超过 20px → 原生 OLE 拖放（阻塞至投放或取消）
        MouseArea {
            id: dragArea
            anchors.fill: spriteImage
            hoverEnabled: true
            property bool armed: false
            property point startPos: Qt.point(0, 0)
            cursorShape: root.moveMode ? Qt.SizeAllCursor : (pet.dragging ? Qt.DragCopyCursor : Qt.OpenHandCursor)

            onPressed: function(mouse) {
                if (root.moveMode || (mouse.modifiers & Qt.AltModifier)) {
                    armed = false
                    root.startSystemMove()
                    return
                }
                startPos = Qt.point(mouse.x, mouse.y)
                armed = true
            }
            onDoubleClicked: function(mouse) {
                armed = false
                root.moveMode = !root.moveMode
            }
            onPositionChanged: function(mouse) {
                if (!armed || !pressedButtons) {
                    return
                }
                var dx = mouse.x - startPos.x
                var dy = mouse.y - startPos.y
                if (Math.abs(dx) + Math.abs(dy) > 20) {
                    armed = false
                    pet.dragCurrent()
                }
            }
            onReleased: armed = false
            onCanceled: armed = false
        }

        //移动模式提示：可点击退出，也可按 Esc。
        Rectangle {
            id: moveHint
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.topMargin: 5
            width: Math.min(root.width - 14, hintText.implicitWidth + 26)
            height: 30
            radius: 15
            visible: root.moveMode
            color: hintArea.containsMouse ? "#f22b7fbf" : "#e31a527f"
            border.width: 1
            border.color: root.iceBlue

            Text {
                id: hintText
                anchors.centerIn: parent
                text: "✥ 移动模式 · 点击退出"
                color: "#ffffff"
                font.pixelSize: 11
                font.bold: true
                elide: Text.ElideRight
            }

            MouseArea {
                id: hintArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.moveMode = false
            }
        }

        //左上角序号指示（如 2 / 3）
        Rectangle {
            id: counterPill
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.margins: 4
            height: 22
            width: counterText.implicitWidth + 16
            radius: 11
            visible: root.controlsVisible && pet.count > 0
            color: root.panelColor

            Text {
                id: counterText
                anchors.centerIn: parent
                text: (pet.index + 1) + " / " + pet.count
                color: "#ffffff"
                font.pixelSize: 11
            }
        }

        //窗口操作收到右上角，不占用小尺寸的底部主操作位。
        Row {
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: 4
            spacing: 3
            visible: root.controlsVisible && !root.moveMode

            Rectangle {
                width: 26; height: 26; radius: 13
                color: hideButton.containsMouse ? root.panelHover : root.panelColor
                Text { anchors.centerIn: parent; text: "—"; color: "white"; font.pixelSize: 12 }
                MouseArea {
                    id: hideButton; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.showMinimized()
                }
                ToolTip.visible: hideButton.containsMouse
                ToolTip.text: "隐藏取用精灵"
            }
            Rectangle {
                width: 26; height: 26; radius: 13
                color: closeButton.containsMouse ? "#e05268" : root.panelColor
                Text { anchors.centerIn: parent; text: "×"; color: "white"; font.pixelSize: 15 }
                MouseArea {
                    id: closeButton; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        pet.saveGeometry(root.x, root.y, root.width, root.height, pet.sizeTier)
                        Qt.quit()
                    }
                }
                ToolTip.visible: closeButton.containsMouse
                ToolTip.text: "退出"
            }
        }

        //状态提示条（拖动结果等）
        Rectangle {
            id: statusPill
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: controlBar.top
            anchors.margins: 6
            height: 24
            radius: 12
            visible: root.controlsVisible && statusText.text.length > 0
            color: root.panelColor

            Text {
                id: statusText
                anchors.centerIn: parent
                width: parent.width - 16
                text: pet.status
                color: "#ffffff"
                font.pixelSize: 11
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
            }
        }

        //底部主操作：立绘总览在最左，不用再理解“桌宠/取用窗”两个程序。
        Rectangle {
            id: controlBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 6
            height: 42
            radius: 21
            visible: root.controlsVisible
            color: root.panelColor

            Row {
                anchors.fill: parent
                anchors.margins: 4
                spacing: 2

                Rectangle {
                    width: (parent.width - 8) / 5
                    height: parent.height
                    radius: height / 2
                    color: galleryButton.containsMouse || galleryWindow.visible ? root.panelHover : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "▦"
                        color: root.iceBlue
                        font.pixelSize: 17
                        font.bold: true
                    }
                    MouseArea {
                        id: galleryButton
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: galleryWindow.openNearPet()
                    }
                    ToolTip.visible: galleryButton.containsMouse
                    ToolTip.text: "立绘总览"
                }

                Rectangle {
                    width: (parent.width - 8) / 5
                    height: parent.height
                    radius: height / 2
                    color: prevButton.containsMouse ? root.panelHover : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "‹"
                        color: "#ffffff"
                        font.pixelSize: 14
                    }
                    MouseArea {
                        id: prevButton
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: pet.prevSprite()
                    }
                    ToolTip.visible: prevButton.containsMouse
                    ToolTip.text: "上一张"
                }

                Rectangle {
                    width: (parent.width - 8) / 5
                    height: parent.height
                    radius: height / 2
                    color: nextButton.containsMouse ? root.panelHover : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "›"
                        color: "#ffffff"
                        font.pixelSize: 14
                    }
                    MouseArea {
                        id: nextButton
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: pet.nextSprite()
                    }
                    ToolTip.visible: nextButton.containsMouse
                    ToolTip.text: "下一张"
                }

                Rectangle {
                    width: (parent.width - 8) / 5
                    height: parent.height
                    radius: height / 2
                    color: favButton.containsMouse ? root.panelHover : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: pet.favorite ? "★" : "☆"
                        color: pet.favorite ? "#ffd75e" : "#ffffff"
                        font.pixelSize: 15
                    }
                    MouseArea {
                        id: favButton
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: pet.toggleFavorite()
                    }
                    ToolTip.visible: favButton.containsMouse
                    ToolTip.text: pet.favorite ? "取消收藏" : "收藏"
                }

                Rectangle {
                    width: (parent.width - 8) / 5
                    height: parent.height
                    radius: height / 2
                    color: sizeButton.containsMouse ? root.panelHover : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: pet.sizeTier
                        color: root.iceBlue
                        font.pixelSize: 12
                        font.bold: true
                    }
                    MouseArea {
                        id: sizeButton
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            var oldRight = root.x + root.width
                            var oldBottom = root.y + root.height
                            pet.cycleSize()
                            Qt.callLater(function() {
                                root.x = oldRight - root.width
                                root.y = oldBottom - root.height
                            })
                        }
                    }
                    ToolTip.visible: sizeButton.containsMouse
                    ToolTip.text: (pet.sizeTier === "S" ? "小 160×230"
                                  : pet.sizeTier === "L" ? "大 320×460"
                                  : "中 240×345")
                                  + "\n点击切换下一档（小 → 中 → 大）"
                }
            }
        }
    }
}
