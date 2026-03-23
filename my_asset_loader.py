# content     = Load asset loader UI for Maya.
# dependency  = PySide2, shiboken2
# how_to      = Use 'run' function to launch the UI in Maya.
# author      = Magnus Yu <magnusyu.com>

import logging
import re
from pathlib import Path

from scripts.external.Qt import QtWidgets, QtCore, QtGui, QtCompat

import search
import load
import ui_utils
import dcc_context

import importlib
importlib.reload(ui_utils)
importlib.reload(search)
importlib.reload(load)
importlib.reload(dcc_context)

import my_asset_loader_rc

# Force register resources (important in Maya reload sessions)
if hasattr(my_asset_loader_rc, "qCleanupResources"):
    try:
        my_asset_loader_rc.qCleanupResources()
    except Exception:
        pass
if hasattr(my_asset_loader_rc, "qInitResources"):
    my_asset_loader_rc.qInitResources()

# Logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(Path(__file__).stem)


# Get this file's path, pipe that into the format method for the ui file.
python_file_path = Path(__file__)
origin_path = python_file_path.parent
ui_path = origin_path / f"{python_file_path.stem}.ui"
window_name = "pyMyAssetLoader"


# Supported formats
SUPPORTED_GEO = {".fbx", ".obj", ".ma", ".mb"}
SUPPORTED_RIG = {".ma", ".mb"}
SUPPORTED_NATIVE = {".ma", ".mb"}
SUPPORTED_OTHER_FORMATS = {".fbx", ".obj"}

_instance_port = 19871
_quit_msg = b"QUIT"

class AssetLoader(ui_utils.UI):
    closed = QtCore.Signal()

    def __init__(self, ui_name, parent=None):
        super(AssetLoader, self).__init__(ui_name, parent)

        # Load the UI and set it as the central widget
        self.ui = QtCompat.loadUi(str(ui_path))

        self.setCentralWidget(self.ui)
        self.setParent(parent)
        self.setWindowFlags(QtCore.Qt.Window)
        self.setWindowTitle(self.ui.windowTitle())
        self.setWindowIcon(QtGui.QPixmap(":/src/img/my_asset_loader.png"))

        self._project_info = {}
        self._project_sub_folders = {}
        self._asset_details = {}
        self._selected_items = {}
        self._non_selected_items = {}
        self._is_scrubbing = False
        self._default_pixmap = ":/src/img/my_asset_loader_preview.png"
        self.vid_ui = None
        self._load_in_progress = False
        self._load_button_cooldown_timer = None

        self.connect_interface()


    def closeEvent(self, event):
        """Clean up the video player when the main window is closed."""
        if self.vid_player:
            self.vid_player.cleanup()
        QtWidgets.QMainWindow.closeEvent(self, event)

    def connect_interface(self):
        """ Handles all signals/slots when UI is launched.
        """
        # Functions
        self.add_project_combo()
        self.add_asset_tree()

        # Table Widget
        self.ui.table_asset.clearContents()
        self.ui.table_asset.setRowCount(0)
        self.header = self.ui.table_asset.horizontalHeader()
        self.header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        self.header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        self.vertical_header = self.ui.table_asset.verticalHeader()
        self.vertical_header.setVisible(True)
        self.vertical_header.setFixedWidth(10)  # width, not height
        self.vertical_header.setHighlightSections(False)
        self.ui.table_asset.setCornerButtonEnabled(False)
        self.ui.table_asset.resizeColumnsToContents()
        self.apply_table_header_layout()

        # Tree Widget
        self.ui.tree_folder.setHeaderHidden(True)

        # Stretch priorities
        self.ui.splitter.setStretchFactor(0, 0)
        self.ui.splitter.setStretchFactor(1, 1)
        self.ui.splitter.setStretchFactor(2, 0)

        # Search filter
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.filter_asset_table)
        self.search_timer.timeout.connect(self.on_asset_selection)
        self.ui.edit_asset.textChanged.connect(self.queue_table_filter)

        # Signals
        self.ui.tree_folder.itemSelectionChanged.connect(self.on_folder_tree_selection)
        self.ui.btn_load.clicked.connect(self.on_load_asset)
        self.ui.table_asset.itemSelectionChanged.connect(self.on_asset_selection)
        # self.ui.table_asset.currentItemChanged.connect(self.on_asset_selection)

        # Create video player from ui_utils video player class
        self.vid_player = ui_utils.VideoPlayer(attach_to=self.ui.preview_gridLayout)
        self.vid_player.set_display_image(self._default_pixmap)

        self.update_load_button_text()
        self.update_button_enabled_state()

    def apply_table_header_layout(self) -> None:
        """Keep fixed columns readable across Qt5/Qt6 font and DPI differences."""
        table = self.ui.table_asset
        header = table.horizontalHeader()

        # Prevent tiny fixed columns when Qt6 metrics differ from Maya's Qt5.
        header.setMinimumSectionSize(48)

        labels_by_column = {
            1: "DEPT",
            2: "STATUS",
            3: "VERSION",
        }

        metrics = header.fontMetrics()
        for column, label in labels_by_column.items():
            text_width = metrics.horizontalAdvance(label)
            # Include sort arrow and style padding/margins.
            min_width = text_width + 30
            table.setColumnWidth(column, max(table.columnWidth(column), min_width))

    # Project and Asset Loading **************************************************************************************************
    def add_project_combo(self) -> None:
        self.ui.combo_project.clear()
        self._project_info = self.find_project_folder_info()
        logger.info (f"Project info: {self._project_info}")
        for item in self._project_info.keys():
            self.ui.combo_project.addItem(item)

    def find_project_folder_info(self) -> dict:
        """ Find folder information from project path.

        RETURN: Dictionary with project names as keys and their paths as values.
        """
        project_path = search.get_project_path()
        project_folders = search.find_proj_folders(project_path)
        return project_folders

    def add_asset_tree(self) -> None:
        """ Load asset information and populate asset tree widget.
        """
        project_name = self.ui.combo_project.currentText()
        project_path = self._project_info.get(project_name)
        folder_tree = self.find_asset_trees(project_path)
        logger.info (f"Folder tree: {folder_tree}")

        # Populate the tree widget
        if project_path.exists():
            self.ui.tree_folder.clear()
            # self.ui.tree_folder.header().hide()
            self.ui.tree_folder.setHeaderLabels(["Assets"])
            self.populate_tree(self.ui.tree_folder.invisibleRootItem(), folder_tree)

    def populate_tree(self, parent_item:QtGui.QStandardItemModel, folder_tree:dict) -> None:
        """
        Recursively populate tree widget with folder structure.

        ARGS:
            parent_item: The parent tree widget item (QStandardItemModel)
            folder_tree: The folder structure as a dictionary
        """
        folder_icon = QtGui.QIcon()
        folder_icon.addFile(":/src/img/folder_close.png", QtCore.QSize(), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        folder_icon.addFile(":/src/img/folder_open.png", QtCore.QSize(), QtGui.QIcon.Normal, QtGui.QIcon.On)

        for key, value in folder_tree.items():
            item = QtWidgets.QTreeWidgetItem(parent_item)
            item.setText(0, key)
            item.setIcon(0, folder_icon)
            # item.setIcon(0, QtGui.QIcon(":/src/img/folder_closed.png"))
            if isinstance(value, dict):
                self.populate_tree(item, value)

    def find_asset_trees(self, folder_path:Path) -> dict:
        """ Find asset folder trees from project path.

        ARGS:
            folder_path(Path): project folder path

        RETURN: dict of folder tree structure
        """
        self._project_sub_folders = search.find_proj_sub_folders(folder_path)
        folder_tree = search.build_folder_tree(self._project_sub_folders)
        return folder_tree

    def find_asset_details(self, folder_name:str, sub_folder_name:str) -> dict:
        """ Find asset details for a given folder and subfolder. As subfolder is dict within a dict

        ARGS:
            folder_name(str): Main folder name
            sub_folder_name(str): The sub folder name

        RETURN: dict of asset details
        """
        sub_folder_info = search.find_data_by_key(self._project_sub_folders, folder_name)
        if not sub_folder_info:
            return {}

        if sub_folder_name:
            sub_folder_info = search.find_data_by_key(sub_folder_info, sub_folder_name)
            if not sub_folder_info:
                return {}

        asset_folder_path = sub_folder_info.get("path")
        asset_paths = search.find_asset_versions(asset_folder_path)
        asset_details = search.find_asset_details(asset_paths)
        return asset_details

    def on_folder_tree_selection(self) -> None:
        item = self.ui.tree_folder.currentItem()
        if not item:
            return

        par_item = self.ui.tree_folder.currentItem().parent()
        if par_item:
            folder_name = par_item.text(0)
            sub_folder_name = item.text(0)
        else:
            folder_name = item.text(0)
            sub_folder_name = ""

        details = self.find_asset_details(folder_name, sub_folder_name)
        self.add_asset_table_details(details)

    def add_asset_table_details(self, details:dict) -> None:
        """
        ARGS: details: The asset details to populate
        """
        self._asset_details = details
        filter_assets = (".mp4", ".mov", ".jpg", ".jpeg", ".png")

        if not self._asset_details:
            self.ui.table_asset.clearContents()
            self.ui.table_asset.setRowCount(0)
            return

        # Prevent row churn while repopulating; re-enable after all rows/widgets are set.
        self.ui.table_asset.setSortingEnabled(False)

        # Clear existing rows
        self.ui.table_asset.clearContents()
        self.ui.table_asset.setRowCount(0)

        for asset_name, versions in self._asset_details.items():
            if not isinstance(versions, dict):
                continue

            _, ver_info = list(versions.items())[-1]
            asset_type = ver_info.get("asset_type", "")
            asset_status = ver_info.get("status", "")

            if asset_status.lower() != "unpublished" and asset_name.lower().endswith(filter_assets):
                continue

            # Build table rows
            row = self.ui.table_asset.rowCount()
            self.ui.table_asset.insertRow(row)
            asset_item = QtWidgets.QTableWidgetItem(asset_name)
            type_item = QtWidgets.QTableWidgetItem(asset_type)
            status_item = QtWidgets.QTableWidgetItem(asset_status)

            # Non editable flags
            asset_item.setFlags(asset_item.flags() & ~QtCore.Qt.ItemIsEditable)
            type_item.setFlags(QtCore.Qt.ItemIsEnabled)
            status_item.setFlags(QtCore.Qt.ItemIsEnabled)

            # Text alignment
            asset_item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            type_item.setTextAlignment(QtCore.Qt.AlignCenter)
            status_item.setTextAlignment(QtCore.Qt.AlignCenter)

            # Populate table
            self.ui.table_asset.setItem(row, 0, asset_item)
            self.ui.table_asset.setItem(row, 1, type_item)
            self.ui.table_asset.setItem(row, 2, status_item)

            # Use combo box for version selection
            self.add_version_combo(row, list(versions.keys()))

        # Keep vertical header, but no numbers/text
        self.ui.table_asset.setVerticalHeaderLabels(
            [""] * self.ui.table_asset.rowCount()
        )

        # Adjust asset table
        self.ui.table_asset.resizeRowsToContents()
        self.ui.table_asset.resizeColumnsToContents()
        self.apply_table_header_layout()
        self.ui.table_asset.setSortingEnabled(True)
        self.update_load_button_text()
        self.update_button_enabled_state()

    def add_version_combo(self, row:int, versions:list) -> None:
        """ Add a combo box to the version cell in the asset table.

        ARGS:
            row: The row index in the asset table
            versions: List of version strings
        """
        versions.sort()
        combo_box = QtWidgets.QComboBox()
        combo_box.setObjectName("versionCombo")
        combo_box.setEditable(False)
        combo_box.addItems(versions)
        combo_box.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

        # Make the version cell non-selectable and non-editable
        version_item = QtWidgets.QTableWidgetItem()
        version_item.setFlags(QtCore.Qt.ItemIsEnabled)
        self.ui.table_asset.setItem(row, 3, version_item)
        self.ui.table_asset.setCellWidget(row, 3, combo_box)
        combo_box.setCurrentIndex(len(versions)-1)

        # Signal
        combo_box.currentTextChanged.connect(self.on_version_changed)

    def on_version_changed(self, version:str) -> None:
        """ Handles version combo box changes.

                ARGS:
            version: The newly selected version string
        """
        combo_box = self.sender()
        if not isinstance(combo_box, QtWidgets.QComboBox):
            return

        row = -1
        for idx in range(self.ui.table_asset.rowCount()):
            if self.ui.table_asset.cellWidget(idx, 3) is combo_box:
                row = idx
                break

        if row < 0:
            return

        asset_item = self.ui.table_asset.item(row, 0)
        if not asset_item:
            return
        asset_name = asset_item.text()
        self.add_property_view(asset_name, version)
        self.add_video_preview(asset_name, version)
        self.update_asset_row_info(row, asset_name, version)
        self.update_load_button_text()
        self.update_button_enabled_state()

    def update_asset_row_info(self, row:int, name:str, ver_number:str) -> None:
        """
        ARGS:
            row: The row index of the asset in the QTableWidget to update
            name: The name of the asset to find in the asset details
            ver_number: The version number to find in the asset details
        """
        for asset_name, versions in self._asset_details.items():
            if asset_name == name and ver_number in versions:
                ver_info = versions[ver_number]
                asset_type = ver_info.get("asset_type", "")
                asset_status = ver_info.get("status", "")

                self.ui.table_asset.item(row, 1).setText(asset_type)
                self.ui.table_asset.item(row, 2).setText(asset_status)
                break

    # Property and Info Display **************************************************************************************************
    def add_property_view(self, asset_name:str, version:str) -> None:
        """ Populate the property tree with asset version details.

        ARGS:
            asset_name: The name of the asset
            asset_status: The status of the asset
            version: The version of the asset
        """
        self.ui.tree_property.clear()
        skip_keys = ("path", "render_path")

        asset_versions = self._asset_details.get(asset_name, {})
        if not asset_versions:
            return

        version_info = asset_versions.get(version, {})
        if not version_info:
            return

        # Header
        self.ui.tree_property.setHeaderLabels(["Type", "Details"])
        # Populate property tree
        for key, value in version_info.items():
            if key in skip_keys:
                continue
            child = QtWidgets.QTreeWidgetItem(self.ui.tree_property)
            child.setText(0, str(key))
            child.setText(1, str(value))

        self.ui.tree_property.expandAll()

    def add_video_preview(self, asset_name:str, version:str) -> None:
        _, asset_path = self.get_version_info(asset_name, version)

        if version.endswith("0"):
            video_path = asset_path.parent / asset_name
            image_path = asset_path.parent / asset_name
        else:
            video_path = asset_path.parent / f"{asset_path.stem}.mp4"
            image_path = asset_path.parent / f"{asset_path.stem}.jpg"
        self.play_video(video_path, image_path)

    def on_asset_selection(self):
        """ Handle asset table selection changes.
        """
        self.get_selected_items()
        if not self._selected_items:
            self.ui.tree_property.clear()
            self.play_video(None, None)
            self.update_load_button_text()
            self.update_button_enabled_state()
            return

        if len(self._selected_items) == 1:
            for asset_name, info in self._selected_items.items():
                asset_type, asset_status, version = info
                logger.info (f"Selected asset: {asset_name}, type: {asset_type}, status: {asset_status}, version: {version}")
                self.add_property_view(asset_name, version)
                self.add_video_preview(asset_name, version)
        else:
            self.play_video(None, None)

        self.update_load_button_text()
        self.update_button_enabled_state()

    def get_version_number(self, asset_name:str) -> int:
        """ Get the next version number for the given asset name.

        ARGS:
            asset_name: The name of the asset

        RETURN: The next version number as an integer
        """
        similar_prefixes = load.get_similar_prefixes(asset_name)
        if similar_prefixes:
            asset_num = len(similar_prefixes) + 1
        else:
            asset_num = 1
        return asset_num

    def get_version_info(self, asset_name:str, version:str) -> tuple[str, Path]:
        asset_num = self.get_version_number(asset_name)
        asset_prefix = f"{Path(asset_name).stem}_{asset_num:02d}"
        asset_path = self._asset_details[asset_name][version].get("path", {})
        return asset_prefix, asset_path

    def get_media_type(self, file_path:Path) -> str:
        suffix = file_path.suffix.lower()
        video_exts = {".mp4", ".mov", ".avi", ".mkv"}
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

        if suffix in video_exts:
            return "video"
        if suffix in image_exts:
            return "image"
        return "unknown"

    def play_video(self, video_path: Path, image_path: Path) -> None:
        if self.vid_player is None:
            return

        if video_path and video_path.exists() and self.get_media_type(video_path) == "video":
            self.vid_player.play_video(video_path)
            return

        if image_path and image_path.exists() and self.get_media_type(image_path) == "image":
            self.vid_player.set_display_image(image_path)
            return

        self.vid_player.set_display_image(self._default_pixmap)

    # Load Button State and Text *************************************************************************************************
    def is_asset_supported(self, asset_name: str, asset_type: str, version: str) -> bool:
        supported_formats = SUPPORTED_NATIVE | SUPPORTED_OTHER_FORMATS
        if not asset_name or Path(asset_name).suffix not in supported_formats:
            return False

        # Get asset path
        asset_versions = self._asset_details.get(asset_name, {})
        if not asset_versions or version not in asset_versions:
            return False

        asset_path = asset_versions[version].get("path")
        if not asset_path:
            return False

        path_obj = Path(asset_path)
        ext = path_obj.suffix.lower()
        asset_type_lower = (asset_type or "").strip().lower()

        if asset_type_lower == "geo":
            return ext in SUPPORTED_GEO
        elif asset_type_lower == "rig":
            return ext in SUPPORTED_RIG
        else:
            # Generic open: supports .ma, .mb, .fbx, .obj
            return ext in (SUPPORTED_NATIVE | SUPPORTED_OTHER_FORMATS)

    def get_pending_asset_table_info(self) -> dict:
        """Return the same asset set that on_load_asset will process."""
        self.get_selected_items()
        if self._selected_items:
            return self._selected_items

        # self.get_non_selected_items()
        # return self._non_selected_items

    def get_load_action(self, asset_type: str) -> str:
        """Map asset type to the actual operation used by load_asset."""
        normalized = (asset_type or "").strip().lower()
        if normalized == "geo":
            return "IMPORT"
        if normalized == "rig":
            return "LOAD"
        return "OPEN"

    def update_load_button_text(self) -> None:
        """Keep the load button text aligned with the action that will run."""
        actions = set()
        asset_table_info = self.get_pending_asset_table_info()

        if asset_table_info:
            for _, info in asset_table_info.items():
                asset_type = info[0] if info else ""
                actions.add(self.get_load_action(asset_type))

        if not actions or len(self._selected_items) == 0:
            action_label = "LOAD"
            is_plural = False
        elif len(actions) == 1:
            action_label = next(iter(actions))
            is_plural = len(asset_table_info) > 1
        else:
            ordered = [action for action in ("LOAD", "IMPORT", "OPEN") if action in actions]
            action_label = "/".join(ordered)
            is_plural = True

        if dcc_context.is_maya():
            suffix = "ASSETS" if is_plural else "ASSET"
            self.ui.btn_load.setText(f"{action_label} {suffix}")
        else:
            self.ui.btn_load.setText(f"{action_label} A{'SSETS' if is_plural else 'SSET'}")

        if not dcc_context.is_maya():
            self.ui.btn_load.setToolTip("Launch Maya and open the selected asset")

        # Set text to be always bold
        font = self.ui.btn_load.font()
        font.setBold(True)
        self.ui.btn_load.setFont(font)

    def update_button_enabled_state(self) -> None:
        """Enable/disable load button based on asset support."""
        asset_table_info = self.get_pending_asset_table_info()
        all_supported = True

        if asset_table_info:
            for asset_name, info in asset_table_info.items():
                asset_type = info[0] if info else ""
                version = info[2] if len(info) > 2 else ""
                if not self.is_asset_supported(asset_name, asset_type, version):
                    all_supported = False
                    break

        self.ui.btn_load.setEnabled(all_supported)
        if not all_supported:
            font = self.ui.btn_load.font()
            font.setBold(False)
            self.ui.btn_load.setFont(font)
            self.ui.btn_load.setText(f"UNSUPPORTED ASSET{'S' if len(asset_table_info) > 1 else ''}")
            self.ui.btn_load.setToolTip("One or more selected assets have unsupported types or formats.")

        else:
            self.ui.btn_load.setToolTip("Load the selected asset(s)")

    # Asset Loading **************************************************************************************************************
    def on_load_asset(self) -> None:
        """ Handle load asset button click.
        """
        asset_table_info = {}

        # Prevent rapid clicks from spawning multiple Maya instances
        if self._load_in_progress:
            return

        self._load_in_progress = True
        self.ui.btn_load.setEnabled(False)

        # Selected items
        self.get_selected_items()
        if self._selected_items:
            asset_table_info = self._selected_items
            logger.info (f"Selected items: {asset_table_info}")

        else:
            self.get_non_selected_items()
            asset_table_info = self._non_selected_items

        if not asset_table_info:
            self._load_in_progress = False
            self.update_button_enabled_state()
            return

        for asset_name, info in asset_table_info.items():
            asset_type, status, version = info
            logger.info (f"Loading asset: {asset_name}, type: {asset_type}, status: {status}, version: {version}")
            asset_prefix, asset_path = self.get_version_info(asset_name, version)

            logger.info ("self._asset_details: ", self._asset_details)
            logger.info (self._asset_details[asset_name])
            logger.info (self._asset_details[asset_name][version])

            self.load_asset(asset_prefix, asset_type, str(asset_path))

        # Cooldown to prevent spamming in standalone mode
        if not dcc_context.is_maya():
            # Re-enable button after cooldown (2 seconds)
            self._load_button_cooldown_timer = QtCore.QTimer(self)
            self._load_button_cooldown_timer.setSingleShot(True)
            self._load_button_cooldown_timer.timeout.connect(self._reset_load_button)
            self._load_button_cooldown_timer.start(2000)
        else:
            self._load_in_progress = False
            self.update_button_enabled_state()

    def _reset_load_button(self) -> None:
        """Re-enable load button after cooldown period."""
        self._load_in_progress = False
        self.update_button_enabled_state()
        if self._load_button_cooldown_timer:
            self._load_button_cooldown_timer.stop()

    def load_asset(self, asset_prefix:str, asset_type:str, asset_path:str) -> None:
        """ Load the specified asset into the Maya scene.

        ARGS:
            asset_prefix(str): The namespace prefix to use when loading the asset
            asset_type(str): The type of the asset (e.g., "geo", "rig")
            asset_path(str): The file path to the asset
        """
        if not asset_path:
            logger.info (f"Asset path is empty for asset: {asset_prefix}")
            return

        # Standalone: send to running Maya or launch a new instance.
        if dcc_context.is_standalone():
            try:
                result = dcc_context.launch_in_maya(asset_path, asset_type, asset_prefix)
                if result == "port":
                    logger.info(f"Sent to running Maya: {asset_prefix}")
                else:
                    logger.info(f"Launched Maya with: {asset_path}")
            except (FileNotFoundError, OSError) as exc:
                QtWidgets.QMessageBox.warning(self, "Maya Error", str(exc))
            return

        if asset_type == "geo":
            load.load_model(asset_path)

        elif asset_type == "rig":
            load.load_rig(asset_path, asset_prefix)

        else:
            load.open_file(asset_path)

    # Asset table selection and non selection handling ***************************************************************************
    def get_selected_items(self) -> dict:
        """  Get the information of the selected row in the QTableWidget.

        RETURN: A dictionary with the row's data or None if no row is selected.
        """
        self._selected_items = {}

        for table_item in self.ui.table_asset.selectedItems():
            ver = None
            # logger.info(item.row(), item.column(), item.text())
            asset_item = str(self.ui.table_asset.item(table_item.row(),0).text())
            type_item = str(self.ui.table_asset.item(table_item.row(),1).text())
            status_item = str(self.ui.table_asset.item(table_item.row(),2).text())
            ver_item = self.ui.table_asset.cellWidget(table_item.row(),3)

            if ver_item is not None:
                ver = str(self.ui.table_asset.cellWidget(table_item.row(),3).currentText())

            self._selected_items[asset_item] = [type_item, status_item, ver]

    def get_non_selected_items(self) -> dict:
        """ Get the information of the non-selected row in the QTableWidget.

        RETURN: A dictionary with the row's data or None if no row is selected.
        """
        self._non_selected_items = {}

        rows = self.ui.table_asset.rowCount()
        for each in range(0, rows):
            ver = None
            actor = str(self.ui.table_asset.item(each,0).text())
            bind_type = str(self.ui.table_asset.item(each,1).text())
            status_item = str(self.ui.table_asset.item(each,2).text())
            ver_item = self.ui.table_asset.cellWidget(each,3)

            if ver_item is not None:
                ver = str(self.ui.table_asset.cellWidget(each,3).currentText())

            self._non_selected_items[actor] = [bind_type, status_item, ver]

    # Search Asset Table *********************************************************************************************************
    def filter_asset_table(self) -> None:
        """
        Apply text filter to animation table
        """
        text = self.ui.edit_asset.text().strip().lower()
        # Split text if there are spaces or comma
        text = [t for t in re.split(r'[,\s]+', text.strip()) if t]
        if not text:
            for r in range(self.ui.table_asset.rowCount()):
                self.ui.table_asset.setRowHidden(r, False)
            return

        for r in range(self.ui.table_asset.rowCount()):
            row_match = False
            for c in range(self.ui.table_asset.columnCount()):
                item = self.ui.table_asset.item(r, c)
                if item and any(t in item.text().lower() for t in text):
                    row_match = True
                    break
            self.ui.table_asset.setRowHidden(r, not row_match)

    def queue_table_filter(self, text: str) -> None:
        """
        Queue the table filter to avoid filtering every keystroke
        :param: text(str) - Text that QLineEdit emits on change, not used directly
        """
        # Small delay to avoid filtering every keystroke (adjust as needed)
        self.search_timer.start(150)

# DCC Context ********************************************************************************************************************
def run():
    return AssetLoader.run(window_name)


# Standalone mode ****************************************************************************************************************
def _signal_existing_instance() -> bool:
    """Connect to a running instance and ask it to quit. Returns True if signalled."""
    import socket as _socket
    try:
        with _socket.create_connection(("127.0.0.1", _instance_port), timeout=1) as s:
            s.sendall(_quit_msg)
        return True
    except OSError:
        return False


def _start_instance_listener(app: QtWidgets.QApplication) -> None:
    """Listen for a quit signal from a newer instance and close this app when received."""
    import socket as _socket
    import threading

    server = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    server.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 0)
    try:
        server.bind(("127.0.0.1", _instance_port))
    except OSError:
        server.close()
        return

    server.listen(1)

    def _listen():
        try:
            conn, _ = server.accept()
            with conn:
                data = conn.recv(64)
            if data == _quit_msg:
                logger.info("[standalone] Quit signal received — closing.")
                # app.quit() is not thread-safe; use invokeMethod to post to the main thread.
                QtCore.QMetaObject.invokeMethod(app, "quit", QtCore.Qt.QueuedConnection)
        except OSError:
            pass
        finally:
            server.close()

    t = threading.Thread(target=_listen, daemon=True)
    t.start()


def run_standalone():
    import time

    # If an existing instance is running, tell it to quit and wait briefly for it to free the port.
    if _signal_existing_instance():
        logger.info("[standalone] Signalled previous instance to quit. Waiting...")
        time.sleep(1.5)

    app = QtWidgets.QApplication.instance()
    created_app = False
    if app is None:
        app = QtWidgets.QApplication([])
        created_app = True

    # Start background listener so a future launch can close us.
    _start_instance_listener(app)

    ui = AssetLoader.run(window_name, use_maya_parent=False)

    if created_app:
        exec_fn = getattr(app, "exec", None) or getattr(app, "exec_", None)
        if exec_fn is not None:
            exec_fn()

    return ui


if __name__ == "__main__":
    run_standalone()
