import os
import traceback
import inspect

from java.io import File
from java.util import ArrayList
from java.util.logging import Level
from java.lang import String

from org.sleuthkit.autopsy.ingest import (
    IngestModule, IngestMessage, IngestServices,
    DataSourceIngestModule, IngestModuleFactoryAdapter, ModuleDataEvent
)
from org.sleuthkit.autopsy.casemodule import Case
from org.sleuthkit.autopsy.datamodel import ContentUtils
from org.sleuthkit.datamodel import BlackboardAttribute

from TCXDecode import parse_tcx


class TCXActivityIngestFactory(IngestModuleFactoryAdapter):
    moduleName = "TCX Activity Parser"

    def getModuleDisplayName(self):
        return self.moduleName

    def getModuleDescription(self):
        return "Parses TCX fitness activity files and extracts summary activity artifacts."

    def getModuleVersionNumber(self):
        return "2.2"

    def isDataSourceIngestModuleFactory(self):
        return True

    def createDataSourceIngestModule(self, ingestOptions):
        return TCXActivityIngestModule()


class TCXActivityIngestModule(DataSourceIngestModule):

    def __init__(self):
        self.logger = IngestServices.getInstance().getLogger(TCXActivityIngestFactory.moduleName)

    def log(self, level, msg):
        self.logger.logp(level, self.__class__.__name__, inspect.stack()[1][3], msg)

    def startUp(self, context):
        self.context = context
        self.services = IngestServices.getInstance()
        self.moduleNameStr = String(TCXActivityIngestFactory.moduleName)

        self.log(Level.INFO, "[Startup] TCX Parser module initialized.")
        self.services.postMessage(
            IngestMessage.createMessage(
                IngestMessage.MessageType.INFO,
                TCXActivityIngestFactory.moduleName,
                "Module initialized successfully."
            )
        )

    def process(self, dataSource, progressBar):
        progressBar.switchToIndeterminate()

        skCase = Case.getCurrentCase().getSleuthkitCase()
        fileManager = Case.getCurrentCase().getServices().getFileManager()
        caseTemp = Case.getCurrentCase().getTempDirectory()

        tcx_files = fileManager.findFiles(dataSource, "%.tcx")
        if len(tcx_files) == 0:
            tcx_files = fileManager.findFiles(dataSource, "%.TCX")

        num_files = len(tcx_files)
        self.log(Level.INFO, "[Process] Found {0} TCX file(s).".format(num_files))

        if num_files == 0:
            return IngestModule.ProcessResult.OK

        progressBar.switchToDeterminate(num_files)

        try:
            art_type_id = skCase.addArtifactType("TSK_TCX_ACTIVITY", "TCX Activity Summary")
            self.log(Level.INFO, "[ArtifactType] Created new artifact type.")
        except:
            art_type_id = skCase.getArtifactTypeID("TSK_TCX_ACTIVITY")
            self.log(Level.INFO, "[ArtifactType] Using existing artifact type.")

        attr_defs = {
            "TSK_TCX_SPORT": "Sport",
            "TSK_TCX_CREATOR": "Creator",
            "TSK_TCX_DEVICE": "Device",
            "TSK_TCX_START": "Start Time",
            "TSK_TCX_DISTANCE": "Total Distance (km)",
            "TSK_TCX_DURATION": "Duration (min)",
            "TSK_TCX_CALORIES": "Calories",
            "TSK_TCX_AVG_HR": "Average HR (bpm)",
            "TSK_TCX_MAX_HR": "Max HR (bpm)",
            "TSK_TCX_AVG_PACE": "Average Pace (min/km)",
            "TSK_TCX_AVG_SPEED": "Average Speed (km/h)",
            "TSK_TCX_MAX_SPEED": "Max Speed (km/h)",
            "TSK_TCX_AVG_CADENCE": "Average Cadence (spm)",
            "TSK_TCX_LAP_COUNT": "Lap Count",
            "TSK_TCX_START_LAT": "Start Latitude",
            "TSK_TCX_START_LON": "Start Longitude",
            "TSK_TCX_END_LAT": "End Latitude",
            "TSK_TCX_END_LON": "End Longitude"
        }

        for attr_name, label in attr_defs.items():
            try:
                skCase.addArtifactAttributeType(
                    attr_name,
                    BlackboardAttribute.TSK_BLACKBOARD_ATTRIBUTE_VALUE_TYPE.STRING,
                    label
                )
            except:
                pass

        artifact_type_obj = None
        try:
            artifact_type_obj = skCase.getArtifactType("TSK_TCX_ACTIVITY")
        except:
            artifact_type_obj = None

        for i, f in enumerate(tcx_files):
            if self.context.isJobCancelled():
                self.log(Level.WARNING, "[Process] Ingest cancelled by user.")
                return IngestModule.ProcessResult.OK

            tcx_name = f.getName()
            progressBar.progress(tcx_name, int((i + 1) * 100 / num_files))
            local_tcx = os.path.join(caseTemp, tcx_name)

            self.log(Level.INFO, "[Process] Handling TCX file: {0}".format(tcx_name))

            try:
                ContentUtils.writeToFile(f, File(local_tcx))
            except Exception as e:
                self.log(Level.SEVERE, "[CopyError] {0}: {1}".format(tcx_name, str(e)))
                continue

            try:
                parsed = parse_tcx(local_tcx)
            except Exception:
                self.log(Level.SEVERE, "[DecodeError] {0}: {1}".format(tcx_name, traceback.format_exc()))
                continue

            if "error" in parsed:
                self.log(Level.WARNING, "[ParseError] {0}: {1}".format(tcx_name, parsed.get("error")))
                continue

            summary = parsed.get("summary", {})
            gps = parsed.get("gps", {})

            if not summary:
                self.log(Level.WARNING, "[Data] No summary found in {0}".format(tcx_name))
                continue

            try:
                art = f.newArtifact(art_type_id)

                values = {
                    "TSK_TCX_SPORT": str(summary.get("sport", "Unknown")),
                    "TSK_TCX_CREATOR": str(summary.get("creator", "")),
                    "TSK_TCX_DEVICE": str(summary.get("device", "")),
                    "TSK_TCX_START": str(summary.get("start_time", "")),
                    "TSK_TCX_DISTANCE": str(summary.get("total_distance_km", "")),
                    "TSK_TCX_DURATION": str(summary.get("total_timer_time_min", "")),
                    "TSK_TCX_CALORIES": str(summary.get("total_calories", "")),
                    "TSK_TCX_AVG_HR": str(summary.get("average_heart_rate", "")),
                    "TSK_TCX_MAX_HR": str(summary.get("max_heart_rate", "")),
                    "TSK_TCX_AVG_PACE": str(summary.get("average_pace_min_per_km", "")),
                    "TSK_TCX_AVG_SPEED": str(summary.get("average_speed_kmh", "")),
                    "TSK_TCX_MAX_SPEED": str(summary.get("max_speed_kmh", "")),
                    "TSK_TCX_AVG_CADENCE": str(summary.get("average_cadence_spm", "")),
                    "TSK_TCX_LAP_COUNT": str(summary.get("lap_count", "")),
                    "TSK_TCX_START_LAT": str(gps.get("start_lat", "")),
                    "TSK_TCX_START_LON": str(gps.get("start_lon", "")),
                    "TSK_TCX_END_LAT": str(gps.get("end_lat", "")),
                    "TSK_TCX_END_LON": str(gps.get("end_lon", ""))
                }

                for attr_name, value in values.items():
                    art.addAttribute(
                        BlackboardAttribute(
                            skCase.getAttributeType(attr_name),
                            TCXActivityIngestFactory.moduleName,
                            value
                        )
                    )

                self.log(Level.INFO, "[Artifact] Created TCX summary artifact for {0}".format(tcx_name))

                try:
                    if artifact_type_obj is not None:
                        art_list = ArrayList()
                        art_list.add(art)
                        evt = ModuleDataEvent(self.moduleNameStr, artifact_type_obj, art_list)
                        IngestServices.getInstance().fireModuleDataEvent(evt)
                        self.log(Level.INFO, "[Event] Fired ModuleDataEvent for {0}".format(tcx_name))
                    else:
                        self.log(Level.WARNING, "[Event] Artifact type object is None for {0}".format(tcx_name))
                except Exception:
                    self.log(Level.WARNING, "[EventError] {0}".format(traceback.format_exc()))

                IngestServices.getInstance().postMessage(
                    IngestMessage.createMessage(
                        IngestMessage.MessageType.DATA,
                        TCXActivityIngestFactory.moduleName,
                        "Parsed TCX file: {0}".format(tcx_name)
                    )
                )

            except Exception:
                self.log(Level.SEVERE, "[ArtifactError] {0}: {1}".format(tcx_name, traceback.format_exc()))

        self.log(Level.INFO, "[Done] TCX Parser completed successfully.")
        self.services.postMessage(
            IngestMessage.createMessage(
                IngestMessage.MessageType.INFO,
                TCXActivityIngestFactory.moduleName,
                "TCX parsing completed — artifacts available under 'TCX Activity Summary'."
            )
        )

        return IngestModule.ProcessResult.OK


def createModule():
    return TCXActivityIngestFactory()