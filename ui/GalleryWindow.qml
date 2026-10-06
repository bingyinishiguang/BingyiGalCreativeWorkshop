import QtQuick
import QtQuick.Controls

Window {
    id: gallery

    width: 461
    height: 455
    minimumWidth: 329
    minimumHeight: 438
    //移动超过阈值后才启动拖放，避免误把点击当作拖出。

    readonly property int dragStartThreshold: 8
    visible: false
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    modality: Qt.NonModal
    transientParent: null
    title: "冰翼取用精灵 · 立绘总览"

    property var petWindow
    //拖放临时隐藏窗口，由独立状态区分关闭和让位。

    property bool dragging: false
    property int total: 0
    property int nextOffset: 0
    property bool loading: false
    property bool hasMore: false

    property string activeTag: ""
    property string activeGame: ""
    property var availableTags: []
    property var availableGames: []
    //级联下拉的两张表（由后端一次带回，切换筛选不用再发请求）
    property var gameCharacters: ({})
    property var scopedGames: []
    property string activeCharacter: ""
    //「作品 → 角色」全量映射里出现过的所有作品名（下拉的完整候选）
    readonly property var allGameNames: Object.keys(gameCharacters).sort()

    //作品与角色筛选相互约束，可选项来自同一次图库查询。
    function gamesFor(character) {
        if (!character)
            return allGameNames
        var out = []
        for (var game in gameCharacters) {
            var list = gameCharacters[game] || []
            if (list.indexOf(character) !== -1)
                out.push(game)
        }
        out.sort()
        return out
    }

    //"全部角色"时要列出所有角色（去重；同一个角色可能在多部作品里）
    function characterPool() {
        var seen = {}
        var out = []
        for (var game in gameCharacters) {
            var list = gameCharacters[game] || []
            for (var i = 0; i < list.length; i++) {
                if (!seen[list[i]]) {
                    seen[list[i]] = true
                    out.push(list[i])
                }
            }
        }
        out.sort()
        return out
    }

    //选了作品 → 只列这部作品的角色；没选 → 全部角色
    function charactersFor(game) {
        return game ? (gameCharacters[game] || []) : characterPool()
    }

    //候选集合变化后恢复当前筛选项。
    function syncFilterIndexes() {
        var games = gamesFor(activeCharacter)
        gameFilter.currentIndex = activeGame ? games.indexOf(activeGame) + 1 : 0
        var characters = charactersFor(activeGame)
        characterFilter.currentIndex = activeCharacter ? characters.indexOf(activeCharacter) + 1 : 0
    }
    //总览窗口几何（跨屏记忆；由 pet.galleryRect / saveGalleryRect 读写）
    property bool geometryLoaded: false
    //搜索框宽度与下方筛选控件总宽度一致。
    readonly property int colGap: 8
    readonly property int rowGap: 8
    //右侧那一列（抓手 / 面部按钮）的宽度随窗口自适应
    readonly property int rightColWidth:
        Math.max(30, Math.min(42, Math.round(width * 0.095)))
    //左侧一列（搜索框 / 三个下拉）宽度由窗口宽度算出，不写死
    readonly property int filterRowWidth:
        Math.max(160, Math.round(width) - 16 - 16 - rightColWidth - colGap)
    //第二行三个下拉（作品 / 角色 / 收藏与标签）。
    readonly property int filterColumns: 3
    readonly property real filterCellWidth:
        (filterRowWidth - (filterColumns - 1) * colGap) / filterColumns
    //「只看脸部」开关：卡片预览放大到头部区域（挑表情用）。
    property bool faceOnly: false
    readonly property int maxChipWidth: 132
    readonly property color ink: "#173b60"
    readonly property color muted: "#6685a4"
    readonly property color accent: "#2d8bd4"
    readonly property color frost: "#f4fbff"
    //收藏筛选独立保存，避免下拉选项调整后索引含义变化。
   property bool filterFavorite: false
    readonly property bool favoriteOnly: filterFavorite

    //卡片高度需覆盖图片、名称与说明，避免文字重叠。
    readonly property int cardCellHeight: 182
    readonly property int cardMargin: 5
    readonly property int cardPadding: 7
    readonly property int cardImageHeight: 112
    readonly property int cardTitleGap: 7
    readonly property int cardTitleHeight: 16
    readonly property int cardDetailGap: 2
    readonly property int cardDetailHeight: 14
    //卡片内容所需高度（含 cell 外边距与卡片内边距，含标题/说明之间的间隔）
    readonly property int cardContentHeight: cardMargin + cardPadding + cardImageHeight
            + cardTitleGap + cardTitleHeight + cardDetailGap + cardDetailHeight
            + cardPadding + cardMargin

    onVisibleChanged: {
        //桌宠可见性由主窗口统一管理。
        if (dragging)
            return
        if (visible)
            resetGallery()
    }

    ListModel { id: spriteModel }

    function positionNearPet() {
        if (!petWindow)
            return
        var position = JSON.parse(pet.galleryPosition(
            petWindow.x, petWindow.y, petWindow.width, petWindow.height,
            gallery.width, gallery.height
        ))
        gallery.x = position.x
        gallery.y = position.y
    }

    function openNearPet() {
        if (visible) {
            hide()
            return
        }
        restoreGeometry()
        positionNearPet()
        show()
        raise()
        applyTopmostWithRetry()
        requestActivate()
        searchInput.forceActiveFocus()
    }

    function resetGallery() {
        spriteModel.clear()
        total = 0
        hasMore = false
        nextOffset = 0
        loadPage(0)
    }

    //标签芯片 / 分类下拉改变时统一走这里：清空网格重新拉第一页。
    function setTag(tag) {
        activeTag = (activeTag === tag) ? "" : tag   //再点一次取消筛选
        resetGallery()
    }

    function restoreGeometry() {
        if (geometryLoaded)
            return
        var saved = JSON.parse(pet.galleryRect())
        if (saved && saved.width > 0 && saved.height > 0) {
            gallery.width = saved.width
            gallery.height = saved.height
            gallery.x = saved.x
            gallery.y = saved.y
        }
        geometryLoaded = true
    }


    function applyTopmostWithRetry() {
        topmostRetry.attempts = 0
        topmostRetry.interval = 60
        topmostRetry.restart()
    }

    function loadPage(offset) {
        if (loading)
            return
        loading = true
        var payload
        try {
            payload = JSON.parse(pet.queryGallery(searchInput.text, favoriteOnly, offset,
                                                  activeTag, activeGame, activeCharacter))
        } catch (error) {
            loading = false
            //图库加载异常写入日志，便于定位空白列表。

            pet.logGalleryGeometry("loadPageError", String(error), 0, 0, 0, 0)
            return
        }
        total = payload.total || 0
        hasMore = payload.hasMore === true
        nextOffset = payload.nextOffset || 0
        if (payload.tags) {
            //作品与角色筛选相互约束。
            availableTags = (payload.tags || []).filter(function (name) {
                return String(name).indexOf("姿势:") !== 0
            })
        }
        if (payload.games)
            availableGames = payload.games
        if (payload.gameCharacters)
            gameCharacters = payload.gameCharacters
        if (payload.scopedGames)
            scopedGames = payload.scopedGames
        syncFilterIndexes()
        for (var i = 0; i < payload.items.length; ++i) {
            var item = payload.items[i]
            spriteModel.append({
                spriteId: item.id,
                spriteTitle: item.title,
                spriteDetail: item.detail,
                spriteFavorite: item.favorite,
                spriteImageUrl: item.imageUrl,
                //头部特写：与缩略图同源，后端多裁一刀并放大到 256。
                spriteHeadUrl: item.headUrl || item.imageUrl,
                spriteTags: (item.tags || []).join(" · "),
                spriteSelected: item.selected
            })
        }
        loading = false
    }

    function markSelected(itemId) {
        for (var i = 0; i < spriteModel.count; ++i)
            spriteModel.setProperty(i, "spriteSelected", spriteModel.get(i).spriteId === itemId)
    }

    Timer {
        id: searchDelay
        interval: 220
        onTriggered: gallery.resetGallery()
    }

    //窗口几何变化后防抖保存，恢复时按可用屏幕范围校正。
    Timer {
        id: geometrySaver
        interval: 500
        onTriggered: {
            if (gallery.visibility !== Window.Minimized && gallery.visibility !== Window.Hidden)
                pet.saveGalleryRect(gallery.x, gallery.y, gallery.width, gallery.height)
        }
    }

    //窗口显示后有界重试置顶，等待原生句柄就绪。
    Timer {
        id: topmostRetry
        property int attempts: 0
        interval: 60
        repeat: false
        onTriggered: {
            pet.setGalleryTopmost(true)
            attempts += 1
            if (attempts < 3) {
                interval = attempts === 1 ? 140 : 300
                restart()
            }
        }
    }
    onXChanged: if (geometryLoaded) geometrySaver.restart()
    onYChanged: if (geometryLoaded) geometrySaver.restart()
    onWidthChanged: if (geometryLoaded) geometrySaver.restart()
    onHeightChanged: if (geometryLoaded) geometrySaver.restart()
    onClosing: if (geometryLoaded) pet.saveGalleryRect(gallery.x, gallery.y, gallery.width, gallery.height)

    Rectangle {
        anchors.fill: parent
        radius: 22
        color: "#f8fcff"
        border.width: 1
        border.color: "#88c9ef"

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: 21
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#ffffff" }
                GradientStop { position: 0.48; color: "#f4faff" }
                GradientStop { position: 1.0; color: "#eaf6ff" }
            }
        }

        //冰翼蓝顶栏：窗口可从空白区拖动。
        Rectangle {
            id: titleBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 1
            height: 68
            radius: 21
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#174d79" }
                GradientStop { position: 0.58; color: "#246fa8" }
                GradientStop { position: 1.0; color: "#62bce8" }
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 82
                anchors.verticalCenter: parent.verticalCenter
                text: "❄"
                color: "#2fffffff"
                font.pixelSize: 52
                rotation: 12
            }

            Image {
                id: brandAvatar
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                width: 42
                height: 42
                source: "avatar-fox-round.png"
                fillMode: Image.PreserveAspectCrop
                smooth: true
            }
            Column {
                anchors.left: brandAvatar.right
                anchors.leftMargin: 11
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1
                Text { text: "冰翼取用精灵"; color: "white"; font.pixelSize: 17; font.bold: true }
                Text { text: "立绘总览 · 点击即切换"; color: "#cfeeff"; font.pixelSize: 11 }
            }
            //拖放期间自动让位，结束后恢复置顶。
            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 54
                anchors.verticalCenter: parent.verticalCenter
                width: 34; height: 34; radius: 17
                color: pinArea.containsMouse ? "#3ad0a0a0" : "#24ffffff"
                Text { anchors.centerIn: parent; text: "设"; color: "white"; font.pixelSize: 13 }
                MouseArea {
                    id: pinArea; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: pet.pinDefaultPosition()
                }
                ToolTip.visible: pinArea.containsMouse
                ToolTip.text: "把桌宠当前位置设为默认"
            }
            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                width: 34; height: 34; radius: 17
                color: closeArea.containsMouse ? "#e0576b" : "#24ffffff"
                Text { anchors.centerIn: parent; text: "×"; color: "white"; font.pixelSize: 18 }
                MouseArea {
                    id: closeArea; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: gallery.hide()
                }
            }
            MouseArea {
                anchors.fill: parent
                anchors.rightMargin: 100   //让开「设」与「×」两个按钮
                onPressed: gallery.startSystemMove()
            }
        }

        Rectangle {
            id: resizeGrip
            objectName: "resizeGrip"
            width: gallery.rightColWidth
            //只占第一行的高度（第二行要从游戏下拉的 top 开始，中间还有 rowGap）。
            height: 42 + gallery.rowGap
            anchors.right: parent.right
            anchors.rightMargin: 16        //与「面部」按钮右边缘严格齐平
            anchors.top: parent.top
            anchors.topMargin: titleBar.height + 14
            radius: 12
            color: gripArea.containsMouse || gripArea.pressed ? "#dceefc" : "#f4fbff"
            border.width: 1
            border.color: gripArea.containsMouse || gripArea.pressed ? gallery.accent : "#c9e0f1"
            //斜纹柄：三条由长到短的斜线，普通窗口缩放手柄的样子
            Column {
                anchors.centerIn: parent
                spacing: 3
                Repeater {
                    model: 3
                    Rectangle {
                        width: 22 - index * 6
                        height: 2
                        radius: 1
                        color: "#2f7fb4"
                        anchors.right: parent.right
                    }
                }
            }
            MouseArea {
                id: gripArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.SizeFDiagCursor
                onPressed: gallery.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
            }
            ToolTip.visible: gripArea.containsMouse
            ToolTip.text: "拖动改变窗口大小（会自动记住）"
        }


        Rectangle {
            id: searchBox
            //窗口变窄时先保住搜索框的最小宽度，再让"卡片宽度"去承担压缩
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.right: faceToggleButton.left
            anchors.rightMargin: gallery.colGap
            anchors.top: titleBar.bottom
            anchors.topMargin: 14
            height: 42
            radius: 13
            color: "#ffffff"
            border.width: searchInput.activeFocus ? 2 : 1
            border.color: searchInput.activeFocus ? gallery.accent : "#c9e0f1"

            Text { anchors.left: parent.left; anchors.leftMargin: 13; anchors.verticalCenter: parent.verticalCenter; text: "⌕"; color: gallery.accent; font.pixelSize: 18 }
            TextInput {
                id: searchInput
                anchors.left: parent.left
                anchors.leftMargin: 39
                anchors.right: clearSearch.left
                anchors.rightMargin: 5
                anchors.verticalCenter: parent.verticalCenter
                color: gallery.ink
                font.pixelSize: 13
                clip: true
                selectByMouse: true
                onTextChanged: searchDelay.restart()
            }
            Text {
                anchors.left: searchInput.left
                anchors.verticalCenter: parent.verticalCenter
                visible: searchInput.text.length === 0
                text: "搜角色、作品、表情或标签"
                color: "#8da6bc"
                font.pixelSize: 12
            }
            Rectangle {
                id: clearSearch
                anchors.right: parent.right
                anchors.rightMargin: 7
                anchors.verticalCenter: parent.verticalCenter
                width: 26; height: 26; radius: 13
                visible: searchInput.text.length > 0
                color: clearArea.containsMouse ? "#dceefb" : "transparent"
                Text { anchors.centerIn: parent; text: "×"; color: gallery.muted; font.pixelSize: 14 }
                MouseArea { id: clearArea; anchors.fill: parent; hoverEnabled: true; onClicked: searchInput.text = "" }
            }
        }

        //统一筛选栏几何，窗口宽度不足时换行。
        ComboBox {
            id: favoriteToggle
            objectName: "favoriteFilter"
            //三个下拉横向排一排：作品在左，角色居中，只看收藏在右。
            anchors.left: characterFilter.right
            anchors.leftMargin: gallery.colGap
            anchors.verticalCenter: gameFilter.verticalCenter
            width: gallery.filterCellWidth
            height: 42
            //下拉选项统一提供收藏和标签筛选。
            readonly property string allOption: "全部立绘"
            model: ["全部立绘", "只看收藏"].concat(gallery.availableTags)
            currentIndex: 0
            font.pixelSize: 11
            onActivated: {
                if (currentIndex <= 0) {
                    gallery.activeTag = ""
                    gallery.filterFavorite = false
                } else if (currentIndex === 1) {
                    gallery.activeTag = ""
                    gallery.filterFavorite = true
                } else {
                    gallery.filterFavorite = false
                    gallery.activeTag = gallery.availableTags[currentIndex - 2]
                }
                gallery.resetGallery()
            }
            background: Rectangle {
                radius: 10
                color: favoriteToggle.hovered || favoriteToggle.popup.visible ? "#e8f3fd" : "#ffffff"
                border.width: 1
                border.color: favoriteToggle.popup.visible ? gallery.accent : "#c9e0f1"
            }
            contentItem: Text {
                objectName: "favoriteFilterLabel"
                leftPadding: 12
                rightPadding: favoriteToggle.indicator.width + 6
                text: favoriteToggle.displayText
                color: gallery.favoriteOnly ? "#1769a5" : gallery.ink
                font.pixelSize: favoriteToggle.font.pixelSize
                font.bold: gallery.favoriteOnly
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            //用 Text 的隐式尺寸确定箭头布局，避免指示器宽度为零。
            indicator: Text {
                objectName: "favoriteFilterArrow"
                x: favoriteToggle.width - width - 11
                y: favoriteToggle.topPadding + (favoriteToggle.availableHeight - height) / 2
                text: "▾"
                color: gallery.muted
                font.pixelSize: 13
            }
            delegate: ItemDelegate {
                width: favoriteToggle.width - 8
                height: 32
                highlighted: favoriteToggle.highlightedIndex === index
                contentItem: Text {
                    leftPadding: 9; text: modelData; color: gallery.ink
                    font.pixelSize: 11; verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle { radius: 7; color: parent.highlighted ? "#e2f3ff" : "transparent" }
            }
            popup: Popup {
                objectName: "favoriteFilterPopup"
                y: favoriteToggle.height + 3
                width: favoriteToggle.width
                implicitHeight: contentItem.implicitHeight + 8
                padding: 4
                background: Rectangle {
                    objectName: "favoriteFilterPopupBg"
                    radius: 10; color: "#ffffff"; border.width: 1; border.color: "#c9e0f1"
                }
                contentItem: ListView {
                    clip: true; implicitHeight: contentHeight
                    model: favoriteToggle.popup.visible ? favoriteToggle.delegateModel : null
                    currentIndex: favoriteToggle.highlightedIndex
                    ScrollIndicator.vertical: ScrollIndicator { }
                }
            }
        }

        //放在右侧一列，与第一行的缩放手柄同宽同高、右边缘齐平。
        Rectangle {
            id: faceToggleButton
            objectName: "faceToggleButton"
            anchors.left: favoriteToggle.right
            anchors.leftMargin: gallery.colGap
            anchors.verticalCenter: gameFilter.verticalCenter
            width: gallery.rightColWidth
            height: 42
            radius: 10
            color: faceButtonArea.containsMouse ? "#e8f3fd" : "#ffffff"
            border.width: 1
            border.color: gallery.faceOnly ? gallery.accent : "#c9e0f1"
            Text {
                anchors.centerIn: parent
                text: gallery.faceOnly ? "全身" : "面部"
                color: gallery.faceOnly ? "#1769a5" : gallery.ink
                font.pixelSize: 11
                font.bold: gallery.faceOnly
            }
            MouseArea {
                id: faceButtonArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: gallery.faceOnly = !gallery.faceOnly
            }
            ToolTip.visible: faceButtonArea.containsMouse
            ToolTip.text: gallery.faceOnly ? "切回完整立绘" : "只看脸部（挑表情更清楚）"
        }


        ComboBox {
            id: gameFilter
            objectName: "gameFilter"
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.top: searchBox.bottom
            anchors.topMargin: gallery.rowGap
            width: gallery.filterCellWidth
            height: 42
            model: ["全部作品"].concat(gallery.gamesFor(gallery.activeCharacter))
            currentIndex: 0
            font.pixelSize: 11
            onActivated: {
                gallery.activeGame = currentIndex <= 0 ? "" : gallery.gamesFor(gallery.activeCharacter)[currentIndex - 1]
                //作品切换后保留有效角色选择，候选按作品约束。
                //角色本身仍是"全部角色"，所以这里保持 activeCharacter 不动。
                gallery.resetGallery()
            }
            background: Rectangle {
                radius: 10
                color: gameFilter.hovered || gameFilter.popup.visible ? "#e8f3fd" : "#ffffff"
                border.width: 1
                border.color: gameFilter.popup.visible ? gallery.accent : "#c9e0f1"
            }
            contentItem: Text {
                objectName: "gameFilterLabel"
                leftPadding: 10
                rightPadding: gameFilter.indicator.width + 5
                text: gameFilter.displayText
                color: gallery.activeGame ? "#1769a5" : gallery.ink
                font.pixelSize: gameFilter.font.pixelSize
                font.bold: Boolean(gallery.activeGame)
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            indicator: Text {
                x: gameFilter.width - width - 9
                y: gameFilter.topPadding + (gameFilter.availableHeight - height) / 2
                text: "▾"
                color: gallery.muted
                font.pixelSize: 12
            }
            delegate: ItemDelegate {
                width: gameFilter.width - 8
                height: 28
                highlighted: gameFilter.highlightedIndex === index
                contentItem: Text {
                    leftPadding: 9
                    text: modelData
                    color: gallery.ink
                    font.pixelSize: 11
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle { radius: 7; color: parent.highlighted ? "#e2f3ff" : "transparent" }
            }
            popup: Popup {
                y: gameFilter.height + 3
                width: gameFilter.width
                implicitHeight: contentItem.implicitHeight + 8
                padding: 4
                background: Rectangle { radius: 10; color: "#ffffff"; border.width: 1; border.color: "#c9e0f1" }
                contentItem: ListView {
                    clip: true
                    implicitHeight: contentHeight
                    model: gameFilter.popup.visible ? gameFilter.delegateModel : null
                    currentIndex: gameFilter.highlightedIndex
                    ScrollIndicator.vertical: ScrollIndicator { }
                }
            }
        }

        //与作品下拉同一行、同一套样式：作品收窄 → 角色候选跟着收窄。
        ComboBox {
            id: characterFilter
            objectName: "characterFilter"
            anchors.left: gameFilter.right
            anchors.leftMargin: gallery.colGap
            anchors.verticalCenter: gameFilter.verticalCenter
            width: gallery.filterCellWidth
            height: 42
            model: ["全部角色"].concat(gallery.charactersFor(gallery.activeGame))
            currentIndex: 0
            font.pixelSize: 11
            onActivated: {
                gallery.activeCharacter = currentIndex <= 0 ? "" : gallery.charactersFor(gallery.activeGame)[currentIndex - 1]
                gallery.resetGallery()
            }
            background: Rectangle {
                radius: 10
                color: characterFilter.hovered || characterFilter.popup.visible ? "#e8f3fd" : "#ffffff"
                border.width: 1
                border.color: characterFilter.popup.visible ? gallery.accent : "#c9e0f1"
            }
            contentItem: Text {
                objectName: "characterFilterLabel"
                leftPadding: 10
                rightPadding: characterFilter.indicator.width + 5
                text: characterFilter.displayText
                color: gallery.activeCharacter ? "#1769a5" : gallery.ink
                font.pixelSize: characterFilter.font.pixelSize
                font.bold: Boolean(gallery.activeCharacter)
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            indicator: Text {
                x: characterFilter.width - width - 9
                y: characterFilter.topPadding + (characterFilter.availableHeight - height) / 2
                text: "▾"
                color: gallery.muted
                font.pixelSize: 12
            }
            delegate: ItemDelegate {
                width: characterFilter.width - 8
                height: 28
                highlighted: characterFilter.highlightedIndex === index
                contentItem: Text {
                    leftPadding: 9
                    text: modelData
                    color: gallery.ink
                    font.pixelSize: 11
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle { radius: 7; color: parent.highlighted ? "#e2f3ff" : "transparent" }
            }
            popup: Popup {
                y: characterFilter.height + 3
                width: characterFilter.width
                implicitHeight: contentItem.implicitHeight + 8
                padding: 4
                background: Rectangle { radius: 10; color: "#ffffff"; border.width: 1; border.color: "#c9e0f1" }
                contentItem: ListView {
                    clip: true
                    implicitHeight: contentHeight
                    model: characterFilter.popup.visible ? characterFilter.delegateModel : null
                    currentIndex: characterFilter.highlightedIndex
                    ScrollIndicator.vertical: ScrollIndicator { }
                }
            }
        }

        //标签在收藏筛选下拉中展示。
        //芯片与下拉会重复展示同一批标签。


        Text {
            id: resultCaption
            anchors.left: parent.left
            anchors.leftMargin: 19
            anchors.top: gameFilter.bottom
            anchors.topMargin: 9
            text: {
                var scope = gallery.activeTag ? ("标签「" + gallery.activeTag + "」") : ""
                if (gallery.activeGame)
                    scope = scope ? (scope + " · " + gallery.activeGame) : gallery.activeGame
                if (total === 0)
                    return scope ? ("没有符合 " + scope + " 的立绘") : "立绘总览"
                return "共 " + total + " 张" + (scope ? (" · " + scope) : "") + " · 按住图片可拖进剪映"
            }
            color: gallery.muted
            font.pixelSize: 11
        }

        GridView {
            id: grid
            objectName: "spriteGrid"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: resultCaption.bottom
            anchors.bottom: footer.top
            anchors.margins: 12
            anchors.topMargin: 8
            clip: true
            //卡片列数随窗口宽度自适应：宽了 3 列，窄了 2 列。
            readonly property int columns: width >= 520 ? 3 : 2
            cellWidth: width / columns
            //卡片高度必须容下"图 + 名称 + 说明"三块，否则文字会压到卡片外/互相重叠
            cellHeight: gallery.cardCellHeight
            model: spriteModel
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            onContentYChanged: {
                if (gallery.hasMore && !gallery.loading && contentY + height > contentHeight - 260)
                    gallery.loadPage(gallery.nextOffset)
            }

            delegate: Item {
                width: grid.cellWidth
                height: grid.cellHeight
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 5
                    radius: 15
                    color: cardArea.containsMouse ? "#ffffff" : "#f7fbff"
                    border.width: spriteSelected ? 2 : 1
                    border.color: spriteSelected ? gallery.accent : "#d3e6f4"

                    Rectangle {
                        id: imageWell
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 7
                        height: 112
                        radius: 11
                        color: "#eaf4fb"
                        clip: true

                        Rectangle {
                            id: headViewport
                            anchors.top: parent.top
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.topMargin: 3
                            width: parent.width - 6
                            height: parent.height - 6
                            color: "transparent"
                            clip: true

                            Image {
                                id: spritePreview
                                anchors.fill: parent
                                //面部模式用「头部特写」，否则用普通缩略图。
                                source: gallery.faceOnly ? spriteHeadUrl : spriteImageUrl
                                sourceSize: Qt.size(256, 256)
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                                cache: true
                                smooth: true
                            }
                        }
                        Rectangle {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 5
                            width: 22; height: 22; radius: 11
                            visible: spriteFavorite
                            color: "#d9296088"
                            Text { anchors.centerIn: parent; text: "★"; color: "#ffe58a"; font.pixelSize: 12 }
                        }
                        Rectangle {
                            anchors.left: parent.left
                            anchors.bottom: parent.bottom
                            anchors.margins: 5
                            width: selectedText.implicitWidth + 12; height: 20; radius: 10
                            visible: spriteSelected
                            color: "#dd2c86c8"
                            Text { id: selectedText; anchors.centerIn: parent; text: "当前"; color: "white"; font.pixelSize: 10; font.bold: true }
                        }
                    }
                    Text {
                        id: cardTitle
                        objectName: "cardTitle"
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.top: imageWell.bottom; anchors.topMargin: 7
                        anchors.leftMargin: 9; anchors.rightMargin: 9
                        text: spriteTitle
                        color: gallery.ink
                        font.pixelSize: 12
                        font.bold: true
                        elide: Text.ElideRight
                        maximumLineCount: 1
                    }
                    Text {
                        id: cardDetail
                        objectName: "cardDetail"
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.top: cardTitle.bottom; anchors.topMargin: 2
                        anchors.leftMargin: 4; anchors.rightMargin: 4
                        text: spriteDetail
                        color: gallery.muted
                        //作品名允许两行换行，避免长名称被截断。
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    MouseArea {
                        id: cardArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        property point pressPoint: Qt.point(0, 0)
                        property bool armed: false
                        onPressed: function(mouse) { pressPoint = Qt.point(mouse.x, mouse.y); armed = true }
                        onPositionChanged: function(mouse) {
                            if (!armed || !pressedButtons)
                                return
                            var threshold = gallery.dragStartThreshold
                            if (Math.abs(mouse.x - pressPoint.x) + Math.abs(mouse.y - pressPoint.y) > threshold) {
                                armed = false
                                if (pet.selectFromGallery(spriteId)) {
                                    gallery.markSelected(spriteId)
                                    pet.dragCurrent()
                                }
                            }
                        }
                        onReleased: function(mouse) {
                            if (!armed)
                                return
                            armed = false
                            if (pet.selectFromGallery(spriteId))
                                gallery.markSelected(spriteId)
                        }
                        onDoubleClicked: {
                            //双击列表里的人 → 回到桌宠模式
                            armed = false
                            if (pet.selectFromGallery(spriteId)) {
                                gallery.markSelected(spriteId)
                                gallery.hide()
                            }
                        }
                        onCanceled: armed = false
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: !gallery.loading && spriteModel.count === 0
                text: favoriteOnly ? "❄\n还没有收藏的立绘" : "❄\n没找到匹配的立绘"
                color: "#7ca3bf"
                font.pixelSize: 14
                horizontalAlignment: Text.AlignHCenter
                lineHeight: 1.5
            }
        }

        Rectangle {
            id: footer
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 1
            anchors.rightMargin: 1
            anchors.bottomMargin: 1
            height: 42
            radius: 20
            color: "#ecf7ff"
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                text: gallery.loading ? "正在整理立绘…" : ("已显示 " + spriteModel.count + " / " + total)
                color: gallery.muted
                font.pixelSize: 11
            }
            //页脚显示当前像素尺寸，便于调整与复现窗口大小。
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 110
                anchors.verticalCenter: parent.verticalCenter
                text: Math.round(gallery.width) + " × " + Math.round(gallery.height)
                color: "#7fb4d6"
                font.pixelSize: 11
            }
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                text: "冰翼逆时光"
                color: "#5d9bc7"
                font.pixelSize: 10
                font.bold: true
            }
        }
    }

}
