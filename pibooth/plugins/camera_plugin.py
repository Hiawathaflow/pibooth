# -*- coding: utf-8 -*-

import time
import pygame
import pibooth
from pibooth import camera
from pibooth.utils import LOGGER


def get_iso(cfg):
    """Return the (preview, capture) ISO. Outdoors the camera chooses it itself.
    """
    if cfg.get('CAMERA', 'light_mode') == 'outdoor':
        return ('Auto', 'Auto')
    return tuple(cfg.gettuple('CAMERA', 'iso', (int, str), 2))


def apply_preview_brightness(cfg, app):
    """Hand the brightness settings of the live preview to the camera.
    """
    value = cfg.get('CAMERA', 'preview_brightness')
    app.camera.preview_brightness = 'auto' if value.lower() == 'auto' else float(value)
    app.camera.preview_auto_target = cfg.getfloat('CAMERA', 'preview_auto_target')


def apply_iso(cfg, app):
    """Use a changed ISO or light mode without restarting pibooth.
    """
    iso = get_iso(cfg)
    if (app.camera.preview_iso, app.camera.capture_iso) != iso:
        app.camera.preview_iso, app.camera.capture_iso = iso
        if hasattr(app.camera, 'set_config_value'):
            app.camera.set_config_value('imgsettings', 'iso', app.camera.preview_iso)


class CameraPlugin(object):

    """Plugin to manage the camera captures.
    """

    name = 'pibooth-core:camera'

    def __init__(self, plugin_manager):
        self._pm = plugin_manager
        self.count = 0

    @pibooth.hookimpl
    def pibooth_configure(self, cfg):
        cfg.add_option('CAMERA', 'preview_source', 'webcam',
                        "Preview source when a webcam and a DSLR are both connected "
                        "('webcam' or 'dslr')",
                        "Preview source", ['webcam', 'dslr'])
        cfg.add_option('CAMERA', 'capture_trigger', 0,
                        "Seconds before the end of the countdown at which a DSLR capture is "
                        "started, to compensate its shutter lag (0 = at the end)",
                        "Capture trigger", ['0', '0.25', '0.5', '0.75', '1', '1.25', '1.5', '1.75', '2', '2.25', '2.5', '2.75', '3', '4', '5'])
        cfg.add_option('CAMERA', 'preview_brightness', 1.3,
                        "Brightness of the live preview, also on the wait screen "
                        "(1.0 = unchanged, Auto = follows the light), does not affect the pictures",
                        "Preview brightness", ['Auto'] + ['{:.1f}'.format(i / 10) for i in range(5, 31)])
        cfg.add_option('CAMERA', 'preview_auto_target', 120,
                        "Average brightness (0-255) the preview is adjusted to "
                        "when the preview brightness is Auto",
                        "Preview target", [str(i) for i in range(80, 181, 10)])
        cfg.add_option('CAMERA', 'light_mode', 'indoor',
                        "Exposure: 'indoor' uses the fixed ISO, 'outdoor' lets the DSLR choose "
                        "the ISO itself while the light changes",
                        "Light mode", ['indoor', 'outdoor'])
        cfg.add_option('CAMERA', 'photo_autolevels', 1,
                        "Percent of the darkest and brightest pixels ignored when the tonal "
                        "range of the DSLR pictures is stretched (0 = off)",
                        "Photo auto levels", ['0', '0.5', '1', '2', '3', '5'])
        cfg.add_option('CAMERA', 'photo_contrast', 1.1,
                        "Contrast of the DSLR pictures (1.0 = unchanged)",
                        "Photo contrast", ['{:.1f}'.format(i / 10) for i in range(5, 21)])
        cfg.add_option('CAMERA', 'photo_saturation', 1.0,
                        "Color saturation of the DSLR pictures (1.0 = unchanged)",
                        "Photo saturation", ['{:.1f}'.format(i / 10) for i in range(5, 21)])

    @pibooth.hookimpl(hookwrapper=True)
    def pibooth_setup_camera(self, cfg):
        outcome = yield  # all corresponding hookimpls are invoked here
        cam = outcome.get_result()

        if not cam:
            LOGGER.debug("Fallback to pibooth default camera management system")
            cam = camera.find_camera(cfg)

        cam.initialize(get_iso(cfg),
                       cfg.gettyped('CAMERA', 'resolution'),
                       cfg.gettuple('CAMERA', 'rotation', int, 2),
                       cfg.getboolean('CAMERA', 'flip'),
                       cfg.getboolean('CAMERA', 'delete_internal_memory'))
        # Keep the 'Smile!' overlay in the same color as the rest of the UI
        cam.overlay_text_color = cfg.gettyped('WINDOW', 'text_color')
        outcome.force_result(cam)

    @pibooth.hookimpl
    def pibooth_cleanup(self, app):
        app.camera.quit()

    @pibooth.hookimpl
    def state_failsafe_enter(self, app):
        """Reset variables set in this plugin.
        """
        app.capture_date = None
        app.capture_nbr = None
        app.camera.drop_captures()  # Flush previous captures

    @pibooth.hookimpl
    def state_wait_enter(self, app):
        app.capture_date = None
        if len(app.capture_choices) > 1:
            app.capture_nbr = None
        else:
            app.capture_nbr = app.capture_choices[0]

    @pibooth.hookimpl
    def state_choose_do(self, app, events):
        event = app.find_choice_event(events)
        if event:
            if event.key == pygame.K_LEFT:
                app.capture_nbr = app.capture_choices[0]
            elif event.key == pygame.K_RIGHT:
                app.capture_nbr = app.capture_choices[1]

    @pibooth.hookimpl
    def state_preview_enter(self, cfg, app, win):
        LOGGER.info("Show preview before next capture")
        if not app.capture_date:
            app.capture_date = time.strftime("%Y-%m-%d-%H-%M-%S")
        app.camera.capture_trigger = cfg.getfloat('CAMERA', 'capture_trigger')  # Applied without restart
        apply_preview_brightness(cfg, app)
        app.camera.photo_autolevels = cfg.getfloat('CAMERA', 'photo_autolevels')
        app.camera.photo_contrast = cfg.getfloat('CAMERA', 'photo_contrast')
        app.camera.photo_saturation = cfg.getfloat('CAMERA', 'photo_saturation')
        apply_iso(cfg, app)
        app.camera.preview(win)

    @pibooth.hookimpl
    def state_preview_do(self, cfg, app):
        pygame.event.pump()  # Before blocking actions
        if cfg.getboolean('WINDOW', 'preview_countdown'):
            app.camera.preview_countdown(cfg.getint('WINDOW', 'preview_delay'))
        else:
            app.camera.preview_wait(cfg.getint('WINDOW', 'preview_delay'))

    @pibooth.hookimpl
    def state_preview_exit(self, cfg, app):
        if cfg.getboolean('WINDOW', 'preview_stop_on_capture'):
            app.camera.stop_preview()

    @pibooth.hookimpl
    def state_capture_do(self, cfg, app, win):
        effects = cfg.gettyped('PICTURE', 'captures_effects')
        if not isinstance(effects, (list, tuple)):
            # Same effect for all captures
            effect = effects
        elif len(effects) >= app.capture_nbr:
            # Take the effect corresponding to the current capture
            effect = effects[self.count]
        else:
            # Not possible
            raise ValueError("Not enough effects defined for {} captures {}".format(
                app.capture_nbr, effects))

        LOGGER.info("Take a capture")
        if cfg.getboolean('WINDOW', 'flash'):
            with win.flash(cfg.getfloat('WINDOW', 'flash_duration')):  # Manage the window here, have no choice
                app.camera.capture(effect)
        else:
            app.camera.capture(effect)

        self.count += 1

    @pibooth.hookimpl
    def state_capture_exit(self, cfg, app):
        if not cfg.getboolean('WINDOW', 'preview_stop_on_capture'):
            app.camera.stop_preview()

    @pibooth.hookimpl
    def state_processing_enter(self, app):
        self.count = 0
