# content     = Load asset loader UI for Maya.
# dependency  = PySide2, shiboken2
# how_to      = Use 'run' function to launch the UI in Maya.
# author      = Magnus Yu <magnusyu.com>

import sys
import logging
from pathlib import Path

import dcc_context

try:
    import maya.OpenMayaUI as omui
except ImportError:
    omui = None

try:
    import shiboken2 as shiboken
except ImportError:
    try:
        import shiboken6 as shiboken
    except ImportError:
        shiboken = None

import search
import load

from scripts.external.Qt import QtCore, QtWidgets, QtMultimedia, QtMultimediaWidgets, QtGui

import importlib
importlib.reload(search)
importlib.reload(load)

# Logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(Path(__file__).stem)


class UI(QtWidgets.QMainWindow):
    closed = QtCore.Signal()

    def __init__(self, ui_name, parent=None):
        super(UI, self).__init__(parent)
        self.setObjectName(ui_name)


    def closeEvent(self, event):
        """Override the closeEvent to emit a custom signal when the window is closed.
        """
        print ("UI closed")
        self.closed.emit()
        super(UI, self).closeEvent(event)

    @classmethod
    def get_maya_main_window(cls):
        """Return Maya's main window when running in Maya, otherwise None."""
        if not dcc_context.is_maya() or omui is None or shiboken is None:
            return None

        try:
            main_window_ptr = omui.MQtUtil.mainWindow()
        except Exception:
            return None

        if not main_window_ptr:
            return None

        return shiboken.wrapInstance(int(main_window_ptr), QtWidgets.QWidget)

    @classmethod
    def remove_ui(cls, ui_name: str):
        """Remove existing top-level windows with the same object name.
        """
        print(f"Attempting to remove UI: {ui_name}")
        existing_windows = []

        maya_main_window = cls.get_maya_main_window()
        if maya_main_window is not None:
            existing_windows.extend(maya_main_window.findChildren(QtWidgets.QMainWindow, ui_name))

        app = QtWidgets.QApplication.instance()
        if app is not None:
            for widget in app.topLevelWidgets():
                if isinstance(widget, QtWidgets.QMainWindow) and widget.objectName() == ui_name:
                    existing_windows.append(widget)

        # De-duplicate while preserving order.
        seen = set()
        for child in existing_windows:
            widget_id = id(child)
            if widget_id in seen:
                continue
            seen.add(widget_id)

            print(f"Found and closing UI: {child.objectName()}")
            child.setParent(None)
            child.close()
            child.deleteLater()

    @classmethod
    def run(cls, ui_name, parent=None, use_maya_parent=True):
        app = QtWidgets.QApplication.instance()
        created_app = False
        if app is None:
            app = QtWidgets.QApplication(sys.argv)
            created_app = True

        # First, try to remove any existing UI with the same name
        cls.remove_ui(ui_name)

        if parent is None and use_maya_parent:
            parent = cls.get_maya_main_window()
        ui = cls(ui_name, parent)
        ui.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        ui.show()

        # Make sure the window is brought to front in both contexts.
        ui.raise_()
        ui.activateWindow()

        # In standalone mode, start the event loop if this call created the app.
        if created_app and parent is None:
            exec_fn = getattr(app, "exec", None) or getattr(app, "exec_", None)
            if exec_fn is not None:
                exec_fn()

        return ui


class VideoPlayer(QtWidgets.QWidget):
    def __init__(self, parent=None, attach_to=None):
        qt_parent = parent if isinstance(parent, QtWidgets.QWidget) else None
        if attach_to is None and isinstance(parent, (QtWidgets.QWidget, QtWidgets.QLayout)):
            attach_to = parent

        super(VideoPlayer, self).__init__(qt_parent)
        self.player = None
        self._is_scrubbing = False
        self.original_pixmap = None
        self._target_aspect_ratio = 16.0 / 9.0
        self.create_video_player(attach_to)

    def cleanup(self):
        """Clean up resources to prevent errors on close."""
        if self.player:
            self.player.stop()
        if hasattr(self, "media_stack") and self.media_stack:
            self.media_stack.removeEventFilter(self)

    def _set_player_media(self, url: QtCore.QUrl) -> None:
        if self.player is None:
            return

        # Qt6 uses setSource(QUrl); Qt5 uses setMedia(QMediaContent).
        if hasattr(self.player, "setSource"):
            self.player.setSource(url)
        else:
            media_content_cls = getattr(QtMultimedia, "QMediaContent", None)
            if media_content_cls is not None:
                self.player.setMedia(media_content_cls(url))
            else:
                self.player.setMedia(url)

    def _clear_player_media(self) -> None:
        if self.player is None:
            return

        if hasattr(self.player, "setSource"):
            self.player.setSource(QtCore.QUrl())
        else:
            media_content_cls = getattr(QtMultimedia, "QMediaContent", None)
            if media_content_cls is not None:
                self.player.setMedia(media_content_cls())
            else:
                self.player.setMedia(QtCore.QUrl())

    def tinted_standard_icon(self, sp_icon, color="#e0e0e0", size=16):
        """Create a tinted QIcon from a QStyle standard icon."""
        base_icon = self.style().standardIcon(sp_icon)
        pm = base_icon.pixmap(size, size)

        tinted = QtGui.QPixmap(pm.size())
        tinted.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(tinted)
        painter.drawPixmap(0, 0, pm)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QtGui.QColor(color))
        painter.end()

        return QtGui.QIcon(tinted)

    def create_video_player(self, attach_to=None):
        self.preview_container = QtWidgets.QWidget(self)
        self.preview_container.setContentsMargins(0, 0, 0, 0)
        self.preview_container.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.preview_container.installEventFilter(self)

        # Media layer: switch between video and static image fallback.
        self.media_stack = QtWidgets.QStackedWidget(self.preview_container)
        self.media_stack.setContentsMargins(0, 0, 0, 0)
        self.media_stack.installEventFilter(self)
        self.media_stack.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        self.video_widget = QtMultimediaWidgets.QVideoWidget(self.media_stack)
        self.video_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.video_widget.setAspectRatioMode(QtCore.Qt.KeepAspectRatio)

        self.image_label = QtWidgets.QLabel(self.media_stack)
        self.image_label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self.image_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        self.media_stack.addWidget(self.video_widget)
        self.media_stack.addWidget(self.image_label)
        self.media_stack.setCurrentWidget(self.image_label)

        # Slider
        self.video_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.video_slider.setRange(0, 0)
        self.video_slider.setEnabled(False)
        self.video_slider.setStyleSheet(
            """
            QSlider::groove:horizontal {
                border: 0px;
                height: 4px;
                background: #5a5a5a;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #4879b2;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #d9d9d9;
                width: 8px;
                margin: -4px 0;
                border-radius: 3px;
            }
            QSlider::handle:horizontal:hover {
                background: #f0f0f0;
            }
            """
        )
        self.video_slider.sliderPressed.connect(self.on_slider_pressed)
        self.video_slider.sliderReleased.connect(self.on_slider_released)
        self.video_slider.sliderMoved.connect(self.on_slider_moved)

        # Play/Pause Button
        self.play_icon = self.tinted_standard_icon(QtWidgets.QStyle.SP_MediaPlay, "#e0e0e0", 16)
        self.pause_icon = self.tinted_standard_icon(QtWidgets.QStyle.SP_MediaPause, "#e0e0e0", 16)
        self.play_pause_button = QtWidgets.QToolButton(self)
        self.play_pause_button.setIcon(self.play_icon)
        self.play_pause_button.setToolTip("Play")

        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setSpacing(6)
        self.controls_layout.addWidget(self.play_pause_button)
        self.controls_layout.addWidget(self.video_slider, 1)

        self.controls_widget = QtWidgets.QWidget(self.preview_container)
        self.controls_widget.setLayout(self.controls_layout)
        self.controls_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.controls_widget.setMinimumHeight(28)

        preview_layout = QtWidgets.QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        preview_layout.setAlignment(QtCore.Qt.AlignTop)
        preview_layout.addWidget(self.media_stack, 1)
        preview_layout.addWidget(self.controls_widget, 0)

        # if attach_to is not None:
        #     if isinstance(attach_to, QtWidgets.QGridLayout):
        #         attach_to.addWidget(self.video_view, 0, 0)
        #         attach_to.addWidget(self.controls_widget, 1, 0)
        #         attach_to.setRowStretch(0, 1)
        #         attach_to.setRowStretch(1, 0)
        #     else:
        #         # QVBoxLayout / QHBoxLayout
        #         attach_to.addWidget(self.video_view, 1)
        #         attach_to.addWidget(self.controls_widget, 0)

        # Internal layout on self (important)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.preview_container, 1)

        # optional: keep preview area reasonable
        self.preview_container.setMinimumHeight(160)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        # Attach only this container widget
        if attach_to is not None:
            if isinstance(attach_to, QtWidgets.QGridLayout):
                attach_to.addWidget(self, 0, 0)
                attach_to.setRowStretch(0, 1)
                attach_to.setColumnStretch(0, 1)
            else:
                attach_to.addWidget(self)

        self.update_media_area_height()
        self.update_preview_image()
        self.set_controls_visible(False)

        # Signal
        self.play_pause_button.clicked.connect(self.on_play_pause_clicked)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Resize and obj in (self.preview_container, self.media_stack):
            self.update_media_area_height()
            self.update_preview_image()
        return super().eventFilter(obj, event)

    def set_display_image(self, image_path):
        """Display a static image in the video view."""
        self.media_stack.setCurrentWidget(self.image_label)
        self.set_controls_visible(False)
        if self.player is not None:
            self.player.stop()
            self._clear_player_media()

        pixmap = None
        image_path_str = str(image_path)

        # Check if it's a Qt resource path or a file path
        if image_path_str.startswith(':'):
            pixmap = QtGui.QPixmap(image_path_str)
        elif image_path and Path(image_path).exists():
            pixmap = QtGui.QPixmap(image_path_str)

        if pixmap and not pixmap.isNull():
            self.original_pixmap = pixmap  # Store the original, full-resolution pixmap
            if pixmap.height() > 0:
                self._target_aspect_ratio = float(pixmap.width()) / float(pixmap.height())
            self.update_media_area_height()
            self.update_preview_image()
        else:
            self.clear_display()

    def clear_display(self):
        """Clear the display, hiding both video and image."""
        self.media_stack.setCurrentWidget(self.image_label)
        self.set_controls_visible(False)
        self.image_label.clear()
        self.original_pixmap = None
        self.video_slider.setRange(0, 0)
        self.video_slider.setEnabled(False)
        if self.player is not None:
            self.player.stop()
            self._clear_player_media()

    def play_video(self, video_path:Path) -> None:
        if self.player is None:
            self.player = QtMultimedia.QMediaPlayer(self)
            self.player.positionChanged.connect(self.on_player_position_changed)
            self.player.durationChanged.connect(self.on_player_duration_changed)
            self.player.mediaStatusChanged.connect(self.on_media_status_changed)
            if hasattr(self.player, "stateChanged"):
                self.player.stateChanged.connect(self.on_player_state_changed)
            elif hasattr(self.player, "playbackStateChanged"):
                self.player.playbackStateChanged.connect(self.on_player_state_changed)

        if video_path.exists():
            self.media_stack.setCurrentWidget(self.video_widget)
            self.set_controls_visible(True)
            self.video_slider.setEnabled(True)
            self.video_slider.setRange(0, 0)
            self.player.setVideoOutput(self.video_widget)
            url = QtCore.QUrl.fromLocalFile(str(video_path))
            self._set_player_media(url)

            self.player.play()
        else:
            # Clear media if path doesn't exist
            self.clear_display()

    def on_player_position_changed(self, position: int) -> None:
        if not self._is_scrubbing:
            self.video_slider.setValue(position)

    def on_player_duration_changed(self, duration: int) -> None:
        dur = max(0, duration)
        self.video_slider.setRange(0, dur)

    def on_media_status_changed(self, status) -> None:
        if status in (QtMultimedia.QMediaPlayer.LoadedMedia, QtMultimedia.QMediaPlayer.BufferedMedia):
            # If backend exposes native video size via sizeHint, use it to refine aspect.
            hint = self.video_widget.sizeHint()
            if hint.width() > 0 and hint.height() > 0:
                self._target_aspect_ratio = float(hint.width()) / float(hint.height())
                self.update_media_area_height()
        if status == QtMultimedia.QMediaPlayer.EndOfMedia:
            # Keep last frame and stop; user can scrub or press play again.
            if self.player is not None:
                self.player.pause()

    def on_player_state_changed(self, state) -> None:
        is_playing = self._is_playing_state(state)
        if is_playing:
            self.play_pause_button.setIcon(self.pause_icon)
            self.play_pause_button.setToolTip("Pause")
        else:
            self.play_pause_button.setIcon(self.play_icon)
            self.play_pause_button.setToolTip("Play")

    def on_slider_pressed(self) -> None:
        self._is_scrubbing = True

    def on_slider_released(self) -> None:
        self._is_scrubbing = False
        if self.player is not None:
            self.player.setPosition(self.video_slider.value())

    def on_slider_moved(self, position: int) -> None:
        if self.player is not None:
            self.player.setPosition(position)

    def on_play_pause_clicked(self) -> None:
        if self.player is not None:
            state = self._get_player_state()
            if self._is_playing_state(state):
                self.player.pause()
            else:
                self.player.play()

    def _get_player_state(self):
        if self.player is None:
            return None

        if hasattr(self.player, "state"):
            return self.player.state()
        if hasattr(self.player, "playbackState"):
            return self.player.playbackState()
        return None

    def _is_playing_state(self, state) -> bool:
        qmp = QtMultimedia.QMediaPlayer
        playing_states = []

        # Qt5 style enum location
        if hasattr(qmp, "PlayingState"):
            playing_states.append(getattr(qmp, "PlayingState"))

        # Qt6 style enum location
        playback_state_enum = getattr(qmp, "PlaybackState", None)
        if playback_state_enum is not None and hasattr(playback_state_enum, "PlayingState"):
            playing_states.append(getattr(playback_state_enum, "PlayingState"))

        return state in playing_states

    def update_media_area_height(self) -> None:
        if not hasattr(self, "preview_container") or not hasattr(self, "controls_widget"):
            return

        available_width = max(1, self.preview_container.width())
        controls_height = self.controls_widget.sizeHint().height() if self.controls_widget.isVisible() else 0
        available_height = max(1, self.preview_container.height() - controls_height)

        aspect = self._target_aspect_ratio if self._target_aspect_ratio > 0 else (16.0 / 9.0)
        target_height = int(round(available_width / aspect))
        target_height = max(1, min(available_height, target_height))

        self.media_stack.setMinimumHeight(target_height)
        self.media_stack.setMaximumHeight(target_height)

    def set_controls_visible(self, visible: bool) -> None:
        self.controls_widget.setVisible(visible)
        self.update_media_area_height()

    def update_preview_image(self) -> None:
        if not self.original_pixmap or self.original_pixmap.isNull():
            self.image_label.clear()
            return

        target_size = self.media_stack.size()
        width = max(1, target_size.width())
        height = max(1, target_size.height())
        scaled_pixmap = self.original_pixmap.scaled(
            width,
            height,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled_pixmap)


def run():
    return UI.run("pyUIBase")
