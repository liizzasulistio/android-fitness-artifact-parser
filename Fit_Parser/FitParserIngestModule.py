import os
import json
import subprocess
import traceback
import inspect

from java.io import File
from java.util import ArrayList
from java.util.logging import Level
from java.lang import System, String

from org.sleuthkit.autopsy.ingest import (
    IngestModule, IngestMessage, IngestServices,
    DataSourceIngestModule, IngestModuleFactoryAdapter, ModuleDataEvent
)
from org.sleuthkit.autopsy.casemodule import Case
from org.sleuthkit.autopsy.datamodel import ContentUtils
from org.sleuthkit.datamodel import BlackboardAttribute

class FitActivityIngestFactory(IngestModuleFactoryAdapter):
    moduleName = "FIT Activity Parser"

    def getModuleDisplayName(self):
        return self.moduleName

    def getModuleDescription(self):
        return "Parses Garmin/Strava/Zepp FIT files and extracts key fitness activity summaries."

    def getModuleVersionNumber(self):
        return "3.5"

    def isDataSourceIngestModuleFactory(self):
        return True

    def createDataSourceIngestModule(self, ingestOptions):
        return FitActivityIngestModule()

class FitActivityIngestModule(DataSourceIngestModule):

    def __init__(self):
        self.logger = IngestServices.getInstance().getLogger(FitActivityIngestFactory.moduleName)

    def log(self, level, msg):
        self.logger.logp(level, self.__class__.__name__, inspect.stack()[1][3], msg)

    def startUp(self, context):
        self.context = context
        self.services = IngestServices.getInstance()
        self.moduleNameStr = String(FitActivityIngestFactory.moduleName)
        self.log(Level.INFO, "[Startup] FIT Parser module initialized.")
        self.services.postMessage(
            IngestMessage.createMessage(
                IngestMessage.MessageType.INFO,
                FitActivityIngestFactory.moduleName,
                "Module initialized successfully."
            )
        )

# FINDING PYTHON INTERPRETER
    def find_python_executable(self):
        env_path = os.getenv("FIT_PARSER_PYTHON")
        if env_path and os.path.exists(env_path):
            self.log(Level.INFO, "[Python] Using path from FIT_PARSER_PYTHON: {}".format(env_path))
            return env_path

        try:
            output = subprocess.check_output(["py", "-0p"], stderr=subprocess.STDOUT)
            for line in output.decode("utf-8").splitlines():
                line = line.strip()
                if ".exe" in line:
                    exe_path = line.split()[-1].strip()
                    if os.path.exists(exe_path):
                        self.log(Level.INFO, "[Python] Auto-detected via py launcher: {}".format(exe_path))
                        os.environ["FIT_PARSER_PYTHON"] = exe_path
                        return exe_path
        except Exception as e:
            self.log(Level.WARNING, "[Python] 'py -0p' detection failed: {}".format(e))

        for name in ["python3", "python"]:
            for d in os.getenv("PATH", "").split(os.pathsep):
                candidate = os.path.join(d, name)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    try:
                        out = subprocess.check_output([candidate, "--version"], stderr=subprocess.STDOUT)
                        if "Python 3" in out.decode("utf-8"):
                            self.log(Level.INFO, "[Python] Found in PATH: {}".format(candidate))
                            return candidate
                    except:
                        pass

        os_name = System.getProperty("os.name").lower()
        if "win" in os_name:
            poss = [
                r"C:\Python311\python.exe", r"C:\Python312\python.exe",
                r"C:\Program Files\Python311\python.exe", r"C:\Program Files\Python312\python.exe",
                r"C:\ProgramData\Anaconda3\python.exe", r"C:\Users\Public\anaconda3\python.exe"
            ]
        elif "mac" in os_name:
            poss = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        else:
            poss = ["/usr/bin/python3", "/usr/local/bin/python3", "/bin/python3"]

        for p in poss:
            if os.path.exists(p):
                self.log(Level.INFO, "[Python] Found in known path: {}".format(p))
                return p

        bundled = os.path.join(os.path.dirname(__file__), "python_embedded", "python.exe")
        if os.path.exists(bundled):
            self.log(Level.INFO, "[Python] Using bundled embedded Python: {}".format(bundled))
            return bundled

        self.log(Level.SEVERE, "[Python] No valid Python 3 interpreter found.")
        return None


# PROCESSING FIT
    def process(self, dataSource, progressBar):
        progressBar.switchToIndeterminate()
        skCase = Case.getCurrentCase().getSleuthkitCase()
        fileManager = Case.getCurrentCase().getServices().getFileManager()
        case_temp = Case.getCurrentCase().getTempDirectory()

        fit_files = fileManager.findFiles(dataSource, "%.fit")
        if len(fit_files) == 0:
            fit_files = fileManager.findFiles(dataSource, "%.FIT")

        num_files = len(fit_files)
        self.log(Level.INFO, "[Process] Found {} FIT file(s).".format(num_files))
        if num_files == 0:
            return IngestModule.ProcessResult.OK

        progressBar.switchToDeterminate(num_files)
        python_exec = self.find_python_executable()

        if not python_exec:
            self.log(Level.SEVERE, "[Startup] No valid Python interpreter found.")
            self.services.postMessage(
                IngestMessage.createMessage(
                    IngestMessage.MessageType.WARNING,
                    FitActivityIngestFactory.moduleName,
                    "No valid Python interpreter found. Install Python 3+ or set FIT_PARSER_PYTHON."
                )
            )
            return IngestModule.ProcessResult.OK

        self.log(Level.INFO, "[Startup] Using Python interpreter: {}".format(python_exec))

        for i, f in enumerate(fit_files):
            if self.context.isJobCancelled():
                self.log(Level.WARNING, "[Process] Ingest cancelled by user.")
                return IngestModule.ProcessResult.OK

            fit_name = f.getName()
            progressBar.progress(fit_name, int((i + 1) * 100 / num_files))
            local_fit = os.path.join(case_temp, fit_name)
            self.log(Level.INFO, "[Process] Handling FIT file: {}".format(fit_name))

            try:
                ContentUtils.writeToFile(f, File(local_fit))
                self.log(Level.INFO, "[Copy] Saved to {}".format(local_fit))
            except Exception as e:
                self.log(Level.SEVERE, "[CopyError] {}: {}".format(fit_name, e))
                continue

            fit_decode_path = os.path.join(os.path.dirname(__file__), "FitDecode.py")
            cmd = [python_exec, fit_decode_path, local_fit]
            self.log(Level.INFO, "[Decode] Running command: {}".format(" ".join(cmd)))

            try:
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                if not output or not output.strip():
                    self.log(Level.WARNING, "[Decode] No output returned for {}".format(fit_name))
                    continue
                parsed = json.loads(output)
                debug_path = os.path.join(case_temp, fit_name + "_parsed.json")
                with open(debug_path, "wb") as dbg:
                    dbg.write(output)
                self.log(Level.INFO, "[Decode] Successfully parsed {} -> {}".format(fit_name, debug_path))
            except Exception:
                self.log(Level.SEVERE, "[DecodeError] {}: {}".format(fit_name, traceback.format_exc()))
                continue

            summary = parsed.get("summary", {})
            analytics = parsed.get("analytics", {})

            total_km = summary.get("total_distance_km") or analytics.get("total_distance_km")
            duration_min = summary.get("total_timer_time_min")
            if total_km and duration_min and duration_min > 0:
                if not summary.get("average_speed_kmh"):
                    summary["average_speed_kmh"] = round(total_km / (duration_min / 60.0), 2)
                if not summary.get("average_pace_min_per_km"):
                    summary["average_pace_min_per_km"] = round(duration_min / total_km, 2)

            if not summary and not analytics:
                self.log(Level.WARNING, "[Data] No usable data found in {}".format(fit_name))
                continue

            self.log(Level.INFO, "[Data] Summary keys: {}".format(", ".join(summary.keys())))
            self.log(Level.INFO, "[Data] Analytics keys: {}".format(", ".join(analytics.keys())))

            #CREATE ARTIFACTS IN AUTOPSY
            try:
                try:
                    art_type_id = skCase.addArtifactType("TSK_FIT_ACTIVITY", "FIT Activity Summary")
                    self.log(Level.INFO, "[ArtifactType] Created new artifact type.")
                except:
                    art_type_id = skCase.getArtifactTypeID("TSK_FIT_ACTIVITY")
                    self.log(Level.INFO, "[ArtifactType] Using existing artifact type.")

                art = f.newArtifact(art_type_id)

                attributes = {
                    "TSK_FIT_SPORT": ("Sport", str(summary.get("sport", "Unknown"))),
                    "TSK_FIT_SUBSPORT": ("Sub Sport", str(summary.get("sub_sport", ""))),
                    "TSK_FIT_START": ("Start Time", str(summary.get("start_time", ""))),
                    "TSK_FIT_DISTANCE": ("Total Distance (km)", str(round(total_km or 0, 3))),
                    "TSK_FIT_DURATION": ("Duration (min)", str(round(duration_min or 0, 2))),
                    "TSK_FIT_AVG_HR": ("Average HR (bpm)", str(analytics.get("average_heart_rate") or summary.get("average_heart_rate"))),
                    "TSK_FIT_MAX_HR": ("Max HR (bpm)", str(analytics.get("max_heart_rate") or summary.get("max_heart_rate"))),
                    "TSK_FIT_AVG_PACE": ("Average Pace (min/km)", str(summary.get("average_pace_min_per_km") or analytics.get("average_pace_min_per_km"))),
                    "TSK_FIT_AVG_SPEED": ("Average Speed (km/h)", str(summary.get("average_speed_kmh") or analytics.get("average_speed_kmh"))),
                    "TSK_FIT_AVG_CADENCE": ("Average Cadence (spm)", str(analytics.get("average_cadence_spm") or "")),
                    "TSK_FIT_ASCENT": ("Elevation Gain (m)", str(summary.get("total_ascent_m") or 0)),
                    "TSK_FIT_DESCENT": ("Elevation Loss (m)", str(summary.get("total_descent_m") or 0)),
                    "TSK_FIT_CREATOR_DEVICE": ("Creator Device", str(summary.get("creator_device", "")))
                }

                for attr_name, (label, value) in attributes.items():
                    try:
                        skCase.addArtifactAttributeType(
                            attr_name,
                            BlackboardAttribute.TSK_BLACKBOARD_ATTRIBUTE_VALUE_TYPE.STRING,
                            label
                        )
                    except:
                        pass
                    art.addAttribute(
                        BlackboardAttribute(skCase.getAttributeType(attr_name),
                                            FitActivityIngestFactory.moduleName,
                                            value)
                    )

                self.log(Level.INFO, "[Artifact] Created artifact for {}".format(fit_name))

                try:
                    bb_type = skCase.getArtifactType("TSK_FIT_ACTIVITY") or skCase.getArtifactType("FIT Activity Summary")
                    if bb_type is None:
                        self.log(Level.WARNING, "[Event] BlackboardArtifact.Type is None; skipping event.")
                    else:
                        art_list = ArrayList()
                        art_list.add(art)
                        evt = ModuleDataEvent(self.moduleNameStr, bb_type, art_list)
                        IngestServices.getInstance().fireModuleDataEvent(evt)
                except Exception:
                    self.log(Level.WARNING, "[Event] Failed to fire ModuleDataEvent (non-fatal): {}".format(traceback.format_exc()))

                IngestServices.getInstance().postMessage(
                    IngestMessage.createMessage(
                        IngestMessage.MessageType.DATA,
                        FitActivityIngestFactory.moduleName,
                        "Parsed FIT file: {}".format(fit_name)
                    )
                )

            except Exception:
                self.log(Level.SEVERE, "[ArtifactError] {}: {}".format(fit_name, traceback.format_exc()))

        self.log(Level.INFO, "[Done] FIT Parser completed successfully.")
        self.services.postMessage(
            IngestMessage.createMessage(
                IngestMessage.MessageType.INFO,
                FitActivityIngestFactory.moduleName,
                "FIT parsing completed — artifacts available under 'FIT Activity Summary'."
            )
        )

        return IngestModule.ProcessResult.OK

def createModule():
    return FitActivityIngestFactory()