import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QWidget, QWidgetAction, QSlider
from PyQt5.QtCore import Qt
from fbs_runtime.application_context.PyQt5 import ApplicationContext
from shutil import copyfile
import contextlib
import os
import pulsectl

pulse = pulsectl.Pulse("t")


class CadmusPulseInterface:
    @staticmethod
    def cli_command(command):
        if not isinstance(command, list):
            command = [command]
        with contextlib.closing(pulsectl.connect_to_cli()) as s:
            for c in command:
                s.write(c + "\n")

    @staticmethod
    def load_modules(mic_name, mic_rate, cadmus_lib_path):
        print(mic_name)
        print(mic_rate)
        print(cadmus_lib_path)

        pulse.module_load(
            "module-null-sink",
            "sink_name=mic_denoised_out rate=%d "
            "sink_properties=\"device.description='Cadmus Microphone Sink'\""
            % mic_rate,
        )
        pulse.module_load(
            "module-ladspa-sink",
            "sink_name=mic_raw_in sink_master=mic_denoised_out label=noise_suppressor_mono plugin=%s control=%d "
            "sink_properties=\"device.description='Cadmus Raw Microphone Redirect'\""
            % (cadmus_lib_path, CadmusApplication.control_level),
        )

        pulse.module_load(
            "module-loopback",
            "latency_msec=1 source=%s sink=mic_raw_in channels=1" % mic_name,
        )

        pulse.module_load(
            "module-remap-source",
            "master=mic_denoised_out.monitor source_name=denoised "
            "source_properties=\"device.description='Cadmus Denoised Microphone (Use me!)'\"",
        )

        print("Set suppression level to %d" % CadmusApplication.control_level)

    @staticmethod
    def unload_modules():
        CadmusPulseInterface.cli_command(
            [
                "unload-module module-loopback",
                "unload-module module-null-sink",
                "unload-module module-ladspa-sink",
                "unload-module module-remap-source",
            ]
        )


class AudioMenuItem(QAction):
    def __init__(self, text, parent, mic_name, mic_rate):
        super().__init__(text, parent)
        self.mic_name = mic_name
        self.mic_rate = mic_rate
        self.setStatusTip("Use the %s as an input for noise suppression" % text)


class CadmusApplication(QSystemTrayIcon):
    control_level = 50

    def __init__(self, app_context, parent=None):
        QSystemTrayIcon.__init__(self, parent)
        self.app_context = app_context
        self.enabled_icon = QIcon(app_context.get_resource("icon_enabled.png"))
        self.disabled_icon = QIcon(app_context.get_resource("icon_disabled.png"))
        self.cadmus_lib_path = ""

        self.disable_suppression_menu = QAction("Disable Noise Suppression")
        self.enable_suppression_menu = QMenu("Enable Noise Suppression")
        self.level_section = None
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setTickInterval(5)
        self.slider.setMinimum(0)
        self.slider.setMaximum(100)
        self.slider.setValue(CadmusApplication.control_level)
        self.slider.valueChanged.connect(self.slider_valuechange)
        self.exit_menu = QAction("Exit")

        self.gui_setup()
        self.drop_cadmus_binary()

    def get_section_message(self):
        return "Suppression Level: %d" % self.slider.value()

    def slider_valuechange(self):
        CadmusApplication.control_level = self.slider.value()
        self.level_section.setText(self.get_section_message())

    def drop_cadmus_binary(self):
        cadmus_cache_path = os.path.join(os.environ["HOME"], ".cache", "cadmus")
        if not os.path.exists(cadmus_cache_path):
            os.makedirs(cadmus_cache_path)

        self.cadmus_lib_path = os.path.join(cadmus_cache_path, "librnnoise_ladspa.so")

        copyfile(
            self.app_context.get_resource("librnnoise_ladspa.so"), self.cadmus_lib_path
        )

    def gui_setup(self):
        main_menu = QMenu()

        self.disable_suppression_menu.setEnabled(False)
        self.disable_suppression_menu.triggered.connect(self.disable_noise_suppression)

        for src in pulse.source_list():
            mic_menu_item = AudioMenuItem(
                src.description, self.enable_suppression_menu, src.name, src.sample_spec.rate
            )
            self.enable_suppression_menu.addAction(mic_menu_item)
            mic_menu_item.triggered.connect(self.enable_noise_suppression)

        self.exit_menu.triggered.connect(self.quit)

        main_menu.addMenu(self.enable_suppression_menu)
        main_menu.addAction(self.disable_suppression_menu)
        main_menu.addAction(self.exit_menu)

        # Add slider widget
        self.level_section = self.enable_suppression_menu.addSection(self.get_section_message())
        wa = QWidgetAction(self.enable_suppression_menu)
        wa.setDefaultWidget(self.slider)
        self.enable_suppression_menu.addAction(wa)

        self.setIcon(self.disabled_icon)
        self.setContextMenu(main_menu)

    def disable_noise_suppression(self):
        CadmusPulseInterface.unload_modules()
        self.disable_suppression_menu.setEnabled(False)
        self.enable_suppression_menu.setEnabled(True)
        self.setIcon(self.disabled_icon)

    def enable_noise_suppression(self):
        CadmusPulseInterface.load_modules(self.sender().mic_name, self.sender().mic_rate, self.cadmus_lib_path)
        self.setIcon(self.enabled_icon)
        self.enable_suppression_menu.setEnabled(False)
        self.disable_suppression_menu.setEnabled(True)

    def quit(self):
        self.disable_noise_suppression()
        self.app_context.app.quit()


if __name__ == "__main__":
    cadmus_context = ApplicationContext()
    parent_widget = QWidget()

    icon = CadmusApplication(cadmus_context, parent_widget)
    icon.show()

    sys.exit(cadmus_context.app.exec_())
