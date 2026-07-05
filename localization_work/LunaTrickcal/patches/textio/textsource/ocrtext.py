# Trickcal patch: spatial sort + durable region cache for in-game overlay.
import time, copy
from myutils.config import globalconfig
from myutils.utils import checkmd5reloadmodule
import NativeUtils, windows
from gui.rangeselect import rangeadjust
from myutils.wrapper import threader
from myutils.ocrutil import imageCut, ocr_run, ocr_init
import gobject
from qtsymbols import *
from myutils.keycode import vkcode_map
from textio.textsource.textsourcebase import basetext
from ocrengines.baseocrclass import OCRResultParsed
from CVUtils import cvMat
from traceback import print_exc

import trickcal_regions


def imageCutEx(*a):
    img = imageCut(*a)
    succ = True
    if a[0]:
        succ, img = img
    else:
        succ = False
    if img.isNull():
        return img
    if not succ:
        rectX = QRect(a[1], a[2], a[3] - a[1], a[4] - a[2])
        rect2 = windows.GetWindowRect(gobject.base.translation_ui.winid)
        rect = QRect(rect2[0], rect2[1], rect2[2] - rect2[0], rect2[3] - rect2[1])
        if rectX.intersected(rect):
            rect.translate(-a[1], -a[2])
            painter = QPainter(img)
            painter.setBrush(Qt.GlobalColor.white)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(rect)
            painter.end()

    if globalconfig.get("use_ocr_preprocess", False):
        try:
            img = checkmd5reloadmodule(
                gobject.getconfig("ocr_preprocess.py"), "ocr_preprocess"
            ).Process(img)
        except:
            print_exc()
    return img


def _range_sort_key(rm: "rangemanger"):
    rect = getattr(rm, "trickcal_crop_rect", None) or rm.range_ui.getrect()
    if not rect:
        return (99999, 99999)
    (x1, y1), (x2, y2) = rect
    return (y1 + y2) // 2, (x1 + x2) // 2


class rangemanger:
    def __init__(self, ref: "ocrtext", ranges: "list[rangemanger]"):
        self.ref = ref
        self.range_ui = rangeadjust(gobject.base.settin_ui, ranges)
        self.savelastimg: cvMat = None
        self.savelastrecimg: cvMat = None
        self.lastocrtime: float = 0
        self.savelasttext: str = None
        self.trickcal_crop_rect = None

    def __del__(self):
        self.range_ui.closesignal.emit()

    def _ocr_at_rect(self, rect, auto: bool):
        if rect is None:
            return None, None
        crop = trickcal_regions.copy_rect(rect)
        imgr = imageCutEx(
            self.ref.hwnd, crop[0][0], crop[0][1], crop[1][0], crop[1][1]
        )
        if imgr.isNull():
            return crop, None
        result = ocr_run(imgr)
        self.savelastimg = cvMat.fromQImage(imgr)
        if not auto:
            self.savelastrecimg = self.savelastimg
        return crop, result

    def getresmanual(self):
        rect = self.range_ui.getrect()
        if rect is None:
            return
        crop, result = self._ocr_at_rect(rect, False)
        if result is None:
            return
        self.lastocrtime = time.time()
        self.savelasttext = result.textonly
        trickcal_regions.tag_crop(self, crop, self.savelasttext)
        return result

    def getresauto(self):
        rect = self.range_ui.getrect()
        if rect is None:
            return
        crop = trickcal_regions.copy_rect(rect)
        imgr = imageCutEx(
            self.ref.hwnd, crop[0][0], crop[0][1], crop[1][0], crop[1][1]
        )
        ok = True
        if globalconfig["ocr_auto_method_v2"] == "analysis":
            imgr1 = cvMat.fromQImage(imgr)

            image_score = imgr1.MSSIM(self.savelastimg)

            gobject.base.thresholdsett1.emit(str(image_score))
            self.savelastimg = imgr1

            if image_score > globalconfig["ocr_stable_sim_v2"]:

                image_score2 = imgr1.MSSIM(self.savelastrecimg)

                gobject.base.thresholdsett2.emit(str(image_score2))
                if image_score2 > globalconfig["ocr_diff_sim_v2"]:
                    ok = False
                else:
                    self.savelastrecimg = imgr1
            else:
                ok = False
        elif globalconfig["ocr_auto_method_v2"] == "period":
            if time.time() - self.lastocrtime > globalconfig["ocr_interval"]:
                ok = True
            else:
                ok = False
        if ok == False:
            return
        result = ocr_run(imgr)
        t = result.textonly
        self.lastocrtime = time.time()
        sim = NativeUtils.distance(self.savelasttext, t)
        self.savelasttext = t
        if sim < globalconfig["ocr_text_diff"]:
            return
        self.savelasttext = t
        trickcal_regions.tag_crop(self, crop, self.savelasttext)
        return result

    def waitforstable(self):
        rect = self.range_ui.getrect()
        if rect is None:
            return False
        imgr = imageCutEx(self.ref.hwnd, rect[0][0], rect[0][1], rect[1][0], rect[1][1])
        imgr1 = cvMat.fromQImage(imgr)
        image_score = imgr1.MSSIM(self.savelastimg)

        gobject.base.thresholdsett1.emit(str(float(image_score)))
        self.savelastimg = imgr1
        return image_score > globalconfig["ocr_stable_sim2_v2"]


class ocrtext(basetext):
    def hwndChanged(self, hwnd):
        self.hwnd = hwnd

    def init(self):
        self.hwnd = None
        self._pause_state = False
        threader(ocr_init)()
        self.ranges: "list[rangemanger]" = []
        self.gettextthread()

    def clearrange(self):
        self.ranges.clear()
        globalconfig["ocrregions"].clear()
        try:
            import trickcal_overlay

            trickcal_regions.clear_all()
            trickcal_overlay.clear_all()
        except Exception:
            print_exc()

    def leaveone(self):
        self.ranges = self.ranges[-1:]
        if self.ranges:
            self.ranges[0].range_ui.isfocus = False

    def newrangeadjustor(self):
        if len(self.ranges) == 0 or globalconfig["multiregion"]:
            self.ranges.append(rangemanger(self, self.ranges))

    def starttrace(self, pos):
        for _r in self.ranges:
            _r.range_ui.starttrace(pos)

    def traceoffset(self, curr):
        for _r in self.ranges:
            _r.range_ui.traceoffsetsignal.emit(curr)

    def setrect(self, rect):
        self.ranges[-1].range_ui.setrect(rect)
        crop = trickcal_regions.copy_rect(rect)
        if crop:
            self.ranges[-1].trickcal_crop_rect = crop

    def setstyle(self):
        [_.range_ui.setstyle() for _ in self.ranges]

    def showhiderangeui(self, b):
        if b and len(self.ranges) == 0:
            for region in globalconfig["ocrregions"]:
                if region:
                    self.newrangeadjustor()
                    self.setrect(region)
            return
        for _ in self.ranges:
            windows.MouseTrans.unset(_.range_ui.winId())

            if b:
                _r = _.range_ui.getrect()
                if _r:
                    _.range_ui.setrect(_r)
            else:
                _.range_ui.hide()

    @threader
    def gettextthread(self):
        laststate = tuple((0 for _ in range(len(globalconfig["ocr_trigger_events"]))))
        lastevents = copy.deepcopy(globalconfig["ocr_trigger_events"])
        while not self.ending:
            if self._pause_state:
                time.sleep(0.1)
                continue
            if not self.isautorunning:
                time.sleep(0.1)
                continue
            rs = self.getuseranges()
            if not rs:
                time.sleep(0.1)
                continue
            if globalconfig["ocr_auto_method_v2"] == "trigger":
                triggered = False
                this = tuple(
                    (
                        windows.GetAsyncKeyState(vkcode_map[line["vkey"]])
                        for line in globalconfig["ocr_trigger_events"]
                    )
                )
                if lastevents != globalconfig["ocr_trigger_events"]:
                    laststate = this
                    lastevents = copy.deepcopy(globalconfig["ocr_trigger_events"])
                    continue
                for _, line in enumerate(globalconfig["ocr_trigger_events"]):
                    event = line["event"]
                    press = this[_]
                    if ((event == 0) and (laststate[_] == 0) and press) or (
                        (event == 1) and laststate[_] and (press == 0)
                    ):
                        triggered = True
                        break
                laststate = this
                if triggered:
                    if self.hwnd:
                        for _ in range(2):
                            p1 = windows.GetWindowThreadProcessId(self.hwnd)
                            p2 = windows.GetWindowThreadProcessId(
                                windows.GetForegroundWindow()
                            )
                            triggered = p1 == p2
                            if triggered:
                                break
                            time.sleep(0.1)

                if triggered:

                    t1 = time.time()
                    while (not self.ending) and (
                        globalconfig["ocr_auto_method_v2"] == "trigger"
                    ):
                        time.sleep(0.1)
                        if time.time() - t1 >= globalconfig["ocr_trigger_delay"]:
                            break
                    while (not self.ending) and (
                        globalconfig["ocr_auto_method_v2"] == "trigger"
                    ):
                        if self.waitforstablex():
                            break
                        time.sleep(0.1)
                    t = self.getallres(False)
                    if t:
                        self.dispatchtext(t)
                time.sleep(0.01)
            else:
                laststate = tuple(
                    (0 for _ in range(len(globalconfig["ocr_trigger_events"])))
                )
                t = self.getallres(True)
                if t:
                    self.dispatchtext(t)
                time.sleep(0.1)

    def waitforstablex(self):
        for range_ui in self.getuseranges():
            if not range_ui.waitforstable():
                return False
        return True

    def getuseranges(self):
        for r in self.ranges:
            if r.range_ui.isfocus:
                return [r]
        return self.ranges

    def _collect_region_results(self, auto: bool):
        pairs: list[tuple[rangemanger, OCRResultParsed]] = []
        ranges = self.getuseranges() if auto else self.ranges
        for r in ranges:
            if auto:
                res = r.getresauto()
            else:
                res = r.getresmanual()
            if res is None:
                continue
            if res.error:
                res.displayerror()
                return None, None
            pairs.append((r, res))
        if not pairs:
            return None, None
        pairs.sort(key=lambda p: _range_sort_key(p[0]))
        return pairs, "\n".join(p[1].textonly for p in pairs)

    def getallres(self, auto):
        pairs, text = self._collect_region_results(auto)
        if not pairs:
            return
        multi_active = len(self.ranges) > 1
        if multi_active:
            trickcal_regions.remember_multi_regions(pairs)
            import trickcal_overlay

            for rm, res in pairs:
                if res.error or res.result.isocrtranslate:
                    continue
                ko = (res.textonly or "").strip()
                if not ko:
                    continue
                rect = getattr(rm, "trickcal_crop_rect", None) or trickcal_regions.rect_from_range_ui(
                    rm.range_ui
                )
                if not rect:
                    continue
                trickcal_overlay.enqueue_region_translate(rect, ko)
            return None
        if len(pairs) == 1:
            rm, res = pairs[0]
            rect = getattr(rm, "trickcal_crop_rect", None) or trickcal_regions.rect_from_range_ui(
                rm.range_ui
            )
            ko = (res.textonly or "").strip()
            if rect and ko:
                trickcal_regions.remember_for_translate(rect, ko)
            if res.result.isocrtranslate:
                gobject.base.displayinfomessage(ko or text, "<notrans>")
                return None
            return ko or text
        trickcal_regions.remember_multi_regions(pairs)
        import trickcal_overlay

        for rm, res in pairs:
            if res.error or res.result.isocrtranslate:
                continue
            ko = (res.textonly or "").strip()
            if not ko:
                continue
            rect = getattr(rm, "trickcal_crop_rect", None) or trickcal_regions.rect_from_range_ui(
                rm.range_ui
            )
            if not rect:
                continue
            trickcal_overlay.enqueue_region_translate(rect, ko)
        return None

    def gettextonce(self):
        return self.getallres(False)

    def gettextonce_per_region(self):
        pairs, _ = self._collect_region_results(False)
        if not pairs:
            return []
        out = []
        for rm, res in pairs:
            rect = getattr(rm, "trickcal_crop_rect", None) or rm.range_ui.getrect()
            out.append((rect, res.textonly))
        return out

    def pause_recognition(self):
        self._pause_state = True

    def resume_recognition(self):
        self._pause_state = False

    def end(self):
        globalconfig["ocrregions"] = [
            getattr(_, "trickcal_crop_rect", None) or _.range_ui.getrect()
            for _ in self.ranges
        ]
        trickcal_regions.remember_from_config()
        self.ranges.clear()
