#   Copyright (c) 2003-2008 Open Source Applications Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.


from datetime import datetime
from i18n import ChandlerMessageFactory as _
import PyICU

"""
General date/time utility functions

Herein lies: 
- Instances of the PyICU objects related to formatting and parsing date/time-
  related stuff using the current locale. (@@@ eventually, I'd guess that we'll
  have a method here to update these objects when the user changes the current
  locale on the fly...)

"""


class DatetimeFormatter(object):
    """This class works around some issues with timezone dependence of
    PyICU DateFormat objects; for details, see:

    <http://wiki.osafoundation.org/bin/view/Journal/GrantBaillie20050809>

    @ivar dateFormat: A C{PyICU.DateFormat} object, which we want to
      use to parse or format dates/times in a timezone-aware fashion.
    """
    def __init__(self, dateFormat):
        super(DatetimeFormatter, self).__init__()
        self.dateFormat = dateFormat
        
    def parse(self, view, string, referenceDate=None):
        """
        @param string: The date/time string to parse
        @type string: C{str} or C{unicode}

        @param referenceDate: Specifies what timezone to use when
            interpretting the parsed result.
        @type referenceDate: C{datetime}

        @return: C{datetime}
        
        @raises: ICUError or ValueError (The latter occurs because
            PyICU DateFormat objects sometimes claim to parse bogus
            inputs like "06/05/0506/05/05". This triggers an exception
            later when trying to create a C{datetime}).
        """

        tzinfo = None
        if referenceDate is not None:
            tzinfo = referenceDate.tzinfo
            
        if tzinfo is None:
            self.dateFormat.setTimeZone(view.tzinfo.default.timezone)
        else:
            self.dateFormat.setTimeZone(tzinfo.timezone)
        
        self.dateFormat.parse(string)
        calendar = self.dateFormat.getCalendar()
        
        return datetime(
            calendar.get(PyICU.Calendar.YEAR),
            calendar.get(PyICU.Calendar.MONTH) + 1,
            calendar.get(PyICU.Calendar.DATE),
            calendar.get(PyICU.Calendar.HOUR_OF_DAY),
            calendar.get(PyICU.Calendar.MINUTE),
            calendar.get(PyICU.Calendar.SECOND),
            calendar.get(PyICU.Calendar.MILLISECOND) * 1000,
            tzinfo)
        
    def format(self, view, datetime):
        """
        @param datetime: The C{datetime} to format. If it's naive,
            its interpreted as being in the user's default timezone.

        @return: A C{unicode}
        
        @raises: ICUError
        """
        tzinfo = datetime.tzinfo
        if tzinfo is None:
            tzinfo = view.tzinfo.default
        self.dateFormat.setTimeZone(tzinfo.timezone)
        return unicode(self.dateFormat.format(datetime))

def forceFourDigitDates(formatter):
    #""" If this formatter isn't using a 4-digit year, force it to. """
    pattern = formatter.dateFormat.toPattern()
    if pattern.find('yyyy') == -1:
        formatter.dateFormat.applyPattern(pattern.replace('yy','yyyy'))
    return formatter

def forceTwoDigitDates(formatter):
    #""" If this formatter isn't using a 2-digit year, force it to. """
    pattern = formatter.dateFormat.toPattern()
    if pattern.find('yyyy') != -1:
        formatter.dateFormat.applyPattern(pattern.replace('yyyy','yy'))
    return formatter

def forceNoSeconds(formatter):
    #""" If this formatter includes seconds, remove them. """
    pattern = formatter.dateFormat.toPattern()
    secondsIndex = pattern.find('ss') 
    if secondsIndex != -1:
        formatter.dateFormat.applyPattern(pattern[:secondsIndex-1] +
                                          pattern[secondsIndex+2:])
    return formatter

shortDateFormat = forceFourDigitDates(DatetimeFormatter(
    PyICU.DateFormat.createDateInstance(PyICU.DateFormat.kShort)))
mediumDateFormat = forceFourDigitDates(DatetimeFormatter(
    PyICU.DateFormat.createDateInstance(PyICU.DateFormat.kMedium)))                        
shortDateTimeFormat = forceTwoDigitDates(forceNoSeconds(DatetimeFormatter(
    PyICU.DateFormat.createDateTimeInstance(PyICU.DateFormat.kShort))))
shortTimeFormat = DatetimeFormatter(
    PyICU.DateFormat.createTimeInstance(PyICU.DateFormat.kShort))

# L10N: The format for displaying hours and minutes.
#       This value should be changed to match the
#       time logic for the locale.
#
#      For example: If times are displayed with a "." (12.30)
#                   instead of "H:mm" the string should be "H.mm"
durationFormat = PyICU.SimpleDateFormat(_(u"H:mm"))

symbols = PyICU.DateFormatSymbols()
weekdayNames = map(unicode, symbols.getWeekdays())
monthNames = map(unicode, symbols.getMonths())

def weekdayName(when):
    # Get the name of the day for this datetime.
    # Convert python's weekday (Mon=0 .. Sun=6) to PyICU's (Sun=1 .. Sat=7).
    wkDay = ((when.weekday() + 1) % 7) + 1
    return weekdayNames[wkDay]
    
# We want to build hint strings like "mm/dd/yy" and "hh:mm PM", but we don't 
# know the locale-specific ordering of these fields. Format a date with 
# distinct values, then replace the resulting string's pieces with text. 
# (Some locales use 4-digit years, some use two, so we'll handle both.)
# We also get the AM/PM field position, to see if it's empty in this locale,
# for use below.
ampmPosition = PyICU.FieldPosition(PyICU.DateFormat.AM_PM_FIELD)
sampleTime = unicode(shortTimeFormat.dateFormat.format(
                     datetime(2003,10,30,11,45), ampmPosition))

#XXX This value was uppercased as to not conflict with the
#    'mm' (month) entry below and match the "MM" (minutes)
#    casing.
# L10N: Used as part of a string that displays a
#       sample time format to the user.
#       The format in English evaluates to "HH:MM"
#       The value for HH (hours) can be changed
#       to be more locale specific.
sampleTime = sampleTime.replace("11", _(u'HH'))

#XXX This value was uppercased as to not conflict with the
#    'mm' (month) entry below
# L10N: Used as part of a string that displays a
#       sample time format to the user.
#       The format in English evaluates to "HH:MM"
#       The value for MM (minutes) can be changed
#       to be more locale specific.
sampleTime = sampleTime.replace("45", _(u'MM'))

sampleDate = unicode(shortDateFormat.dateFormat.format(
             datetime(2003,10,30)))

# L10N: Used as part of a string that displays a
#       sample date format to the user.
#       The format in English evaluates to "mm/dd/yyyy"
#       The value for yyyy (year) can be changed
#       to be more locale specific.
sampleDate = sampleDate.replace(u"2003", _(u"yyyy"))

# L10N: Used as part of a string that displays a
#       sample date format to the user.
#       The format in English evaluates to "mm/dd/yy"
#       The value for yy (year) can be changed
#       to be more locale specific.
sampleDate = sampleDate.replace(u"03", _(u"yy"))

# L10N: Used as part of a string that displays a
#       sample date format to the user.
#       The format in English evaluates to "mm/dd/yyyy"
#       The value for mm (month) can be changed
#       to be more locale specific.
sampleDate = sampleDate.replace(u"10", _(u"mm"))

# L10N: Used as part of a string that displays a
#       sample date format to the user.
#       The format in English evaluates to "mm/dd/yyyy"
#       The value for dd (day) can be changed
#       to be more locale specific.
sampleDate = sampleDate.replace(u"30", _(u"dd"))

# Ick: getAmPmStrings returns am/pm strings even if the locale doesn't use
# them when formatting dates; so, check an actual format and make the
# name list empty if our times would be formatted that way.
ampmNames = (ampmPosition.getBeginIndex() != ampmPosition.getEndIndex()) \
          and map(unicode, symbols.getAmPmStrings()) or []
