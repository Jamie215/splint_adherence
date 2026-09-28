# Single source of truth for the time zone the app displays and accepts.
#
# The device itself only stores UTC epoch seconds. The GUI interprets the start
# time a researcher enters as Eastern time, and downloaded CSVs / analysis views
# show Eastern wall-clock time (DST-aware). Change this one value to relocate
# the app to a different zone.
import pytz

DISPLAY_TZ_NAME = "America/New_York"
DISPLAY_TZ = pytz.timezone(DISPLAY_TZ_NAME)
