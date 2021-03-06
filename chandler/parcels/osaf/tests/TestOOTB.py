import application.schema as schema
import osaf.pim as pim
import osaf.sharing as sharing
import util.testcase as testcase
from i18n import ChandlerSafeTranslationMessageFactory as translate
from datetime import *
import pkg_resources

def findCollection(view, name):
    sidebar = schema.ns("osaf.app", view).sidebarCollection
    name = translate(name) # search for the localized name
    for coll in sidebar:
        if coll.displayName == name:
            return coll

class OOTBTestCase(testcase.SharedSandboxTestCase):
    """
    Tests that the out-of-the box events and collections are
    created correctly.
    """
    
    def setUp(self):
        super(OOTBTestCase, self).setUp()
        # Make sure the osaf.app parcel is loaded
        schema.parcel_for_module("osaf.app", self.view)
    
    def checkStampness(self, item, *stampClasses):
        for cls in stampClasses:
            self.failUnless(pim.has_stamp(item, cls),
                            "Item %s doesn't have stamp %s" % (item, cls))
            self.failUnless(item in cls.getCollection(self.view),
                            "Item %s is not in collection for stamp %s" %
                                (item, cls))
                                
        self.failUnlessEqual(
            set(pim.Stamp(item).stamp_types),
            set(stampClasses),
            "Unexpected extra classes in stamps %s for item %s" %
                (set(pim.Stamp(item).stamp_types), item)
        )

        
    def getCollection(self, name):
        result = findCollection(self.view, name)
        
        if result is None:
            self.fail("Couldn't find collection %s in sidebar" % (name,))
        
        return result


    def getItem(self, name):
        all = schema.ns("osaf.pim", self.view).allCollection
        name = translate(name) # search for the localized name
        for item in all:
            if item.displayName == name:
                return item
        
        self.fail("Couldn't find item %s in all collection" % (name,))

    def testSidebar(self):
        sidebarCollection = schema.ns("osaf.app", self.view).sidebarCollection
        pim_ns = schema.ns("osaf.pim", self.view)
        
        i = iter(sidebarCollection)
        
        self.failUnless(i.next() is pim_ns.allCollection)
        self.failUnless(i.next() is pim_ns.inCollection)
        self.failUnless(i.next() is pim_ns.outCollection)
        self.failUnless(i.next() is pim_ns.trashCollection)
                        
        self.failUnless(i.next() is self.getCollection(u"Work"))
        self.failUnless(i.next() is self.getCollection(u"Home"))
        self.failUnless(i.next() is self.getCollection(u"Fun"))
        self.failUnless(i.next() is self.getCollection(u"U.S. Holidays"))

        self.failUnlessRaises(StopIteration, i.next)

    def testHolidays(self):
        holidays = self.getCollection(u"U.S. Holidays")
        
        self.failUnless(pim.has_stamp(holidays, sharing.SharedItem))
        self.failUnlessEqual(len(list(sharing.SharedItem(holidays).shares)), 1)

        share = sharing.SharedItem(holidays).shares.first()
        self.failUnless(share.established)
        self.failUnless(isinstance(share.conduit,
                                   sharing.WebDAVMonolithicRecordSetConduit))
    
    def failUnlessHolidayMatches(self, uid, year, month, day):
        holidays = self.getCollection(u"U.S. Holidays")
        event = pim.EventStamp(sharing.findUID(self.view, uid))
        
        self.failUnless(event.itsItem in holidays)
        
        targetDate = date(year, month, day)
        d = datetime.combine(targetDate,
                             time(0, tzinfo=self.view.tzinfo.default))
        matches = event.getOccurrencesBetween(d - timedelta(days=1),
                                              d + timedelta(days=1))
        self.failUnlessEqual(len(matches), 1)
        matchEvent = matches[0]
        self.failUnlessEqual(matchEvent.startTime.date(), targetDate)
        self.failUnless(matchEvent.allDay)
    
    def testChristmas(self):
        self.failUnlessHolidayMatches('2acc9d0a-aedd-57e9-e251-7acd12b6f495',
                                      2012, 12, 25)

    def testFathersDay(self):
        self.failUnlessHolidayMatches('7b9f9601-66a0-3a19-6b01-4c58cab06f0e',
                                      2008, 6, 15)

    def testThanksgiving(self):
        self.failUnlessHolidayMatches('7539adcf-2264-2608-c0be-9dcea56e638b',
                                      2008, 11, 27)
        self.failUnlessHolidayMatches('7539adcf-2264-2608-c0be-9dcea56e638b',
                                      2044, 11, 24)

    def testYearly(self):
        for eventItem in self.getCollection(u"U.S. Holidays"):
            start = datetime.combine(date(2011, 1, 1),
                                     time(0, tzinfo=self.view.tzinfo.default))
            end = datetime.combine(date(2012, 1, 1),
                                   time(0, tzinfo=self.view.tzinfo.default))

            # Skip inauguration day, which is the only non-annual event in there
            if eventItem.icalUID != 'e25af817-2b0c-928e-30b6-bd3feab7db72':
                master = pim.EventStamp(eventItem)
                events = master.getOccurrencesBetween(start, end)
                self.failUnlessEqual(len(events), 1)
                                        


    def testWelcomeEvent(self):
        
        # Look up the welcome event ...
        welcome = schema.ns("osaf.app", self.view).WelcomeEvent
        
        # Check its event-ness ...
        self.checkStampness(welcome, pim.EventStamp, pim.TaskStamp)

        # Check it's in the all collection
        self.failUnless(
            welcome in schema.ns("osaf.pim", self.view).allCollection)
        # ... and two other collections
        self.failUnless(len(list(welcome.appearsIn)), 3)
        
    def testNextDentist(self):
        item = self.getItem(u"Next dentist appointment?")
        self.checkStampness(item, pim.EventStamp)
        self.failUnless(pim.EventStamp(item).anyTime)
        self.failIf(pim.EventStamp(item).allDay)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.now)
        self.failUnless(item.userReminderTime is None)
        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)
        
    def testTellAFriend(self):
        item = self.getItem(u"Tell a friend about Chandler")
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.now)
        self.checkStampness(item)
        self.failUnless(isinstance(item, pim.Note))
        self.failUnless(item.userReminderTime is None)
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 1)
               
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 1)

    def testWriteUp(self):
        item = self.getItem(u"Write-up...")
        self.checkStampness(item, pim.TaskStamp)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.now)
        self.failUnlessEqual(item.lastModification, pim.Modification.created)
        
        self.failUnless(item in self.getCollection(u"Work"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)
        self.failIfEqual(item.body, u'') # non-empty contents

    def testFollowUp(self):
        item = self.getItem(u"Follow up with...on...")

        self.checkStampness(item, pim.TaskStamp)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.now)
                             
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 1)
        self.failIfEqual(item.body, u'') # check for non-empty contents
        
    def testStartPlanningVacation(self):
        item = self.getItem(u"Start planning vacation")
        self.checkStampness(item, pim.TaskStamp)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.now)
        self.failUnlessEqual(item.lastModification, pim.Modification.created)

        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)

    def testBiweeklyStatusReport(self):
        item = self.getItem(u"Bi-Weekly Status Report")
        self.checkStampness(item, pim.TaskStamp, pim.EventStamp)

        self.failUnless(item in self.getCollection(u"Work"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)
        
        masterEvent = pim.EventStamp(item).getMaster()
        self.failUnless(masterEvent.anyTime)
        self.failIf(masterEvent.allDay)
        self.failUnless(masterEvent.userReminderInterval is None)
        firstOccurrence = masterEvent.getFirstOccurrence()
        self.failUnlessEqual(firstOccurrence.itsItem.triageStatus,
                             pim.TriageEnum.now)

        rruleset = masterEvent.rruleset
        self.failUnlessEqual(len(list(rruleset.rrules)), 1)
        self.failUnlessEqual(rruleset.rrules.first().freq, 'weekly')
        self.failUnlessEqual(rruleset.rrules.first().interval, 2)

        # Double-check the bi-weekly thing
        delta = (firstOccurrence.getNextOccurrence().effectiveStartTime - 
                 firstOccurrence.effectiveStartTime)
        self.failUnlessEqual(delta, timedelta(days=14))

    def testOfficeSupplies(self):
        item = self.getItem(u"Office supplies order")
        self.checkStampness(item, pim.EventStamp)

        masterEvent = pim.EventStamp(item).getMaster()
        self.failUnless(masterEvent.anyTime)
        self.failIf(masterEvent.allDay)
        self.failUnless(masterEvent.userReminderInterval is None)
        self.failIfEqual(item.body, u'')
        
        self.failUnless(item in self.getCollection(u"Work"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)

        rruleset = masterEvent.rruleset
        self.failUnlessEqual(len(list(rruleset.rrules)), 1)
        self.failUnlessEqual(rruleset.rrules.first().freq, 'monthly')
        self.failUnlessEqual(rruleset.rrules.first().interval, 1)

    def testSalsaClass(self):
        item = self.getItem(u"Salsa Class")
        self.checkStampness(item, pim.EventStamp)

        masterEvent = pim.EventStamp(item).getMaster()
        self.failIf(masterEvent.anyTime)
        self.failIf(masterEvent.allDay)
        self.failUnless(masterEvent.userReminderInterval is None)
        self.failIfEqual(item.body, u'')
        # Sundays at 2:30 PM
        self.failUnlessEqual(masterEvent.effectiveStartTime.weekday(), 6)
        self.failUnlessEqual(masterEvent.effectiveStartTime.time(),
                             time(14, 30))

        
        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in self.getCollection(u"Fun"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 3)
        
        rruleset = masterEvent.rruleset
        self.failUnlessEqual(len(list(rruleset.rrules)), 1)
        self.failUnlessEqual(rruleset.rrules.first().freq, 'weekly')
        self.failUnlessEqual(rruleset.rrules.first().interval, 1)

        # Should have 2 or 3 DONE modifications (in the past) and
        # one LATER or NOW
        events = sorted(masterEvent.modifications,
                        key=lambda item: pim.EventStamp(item).startTime)
        self.failUnless(len(events) in (3, 4))
        
        ts = [x.triageStatus for x in events]
        self.failUnless(ts[-1] in (pim.TriageEnum.later, pim.TriageEnum.now))
        self.failUnlessEqual(set(ts[:-1]), set([pim.TriageEnum.done]))

    def testDinner(self):
        item = self.getItem(u"Brunch potluck...")
        self.checkStampness(item, pim.EventStamp)
        self.failUnlessEqual(item.lastModification, pim.Modification.created)
        
        # Check Sundays 11h00-13h00
        self.failUnlessEqual(pim.EventStamp(item).startTime.hour, 11)
        self.failUnlessEqual(pim.EventStamp(item).duration,
                             timedelta(hours=2))
        self.failUnlessEqual(pim.EventStamp(item).startTime.date().weekday(),
                             6)
        
        self.failIf(pim.EventStamp(item).allDay)
        self.failIf(pim.EventStamp(item).anyTime)
        self.failUnless(pim.EventStamp(item).rruleset is None)
        self.failUnless(item.userReminderTime is None)
        self.failUnless(pim.EventStamp(item).userReminderInterval is None)

        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in self.getCollection(u"Fun"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 3)

    def testPresents(self):
        item = self.getItem(u"Ideas for presents")
        self.checkStampness(item)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.later)
        self.failUnlessEqual(item.lastModification, pim.Modification.created)
        self.failUnless(item.userReminderTime is None)
        
        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)

    def testThankYous(self):
        item = self.getItem(u"Thank you notes")
        self.checkStampness(item)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.later)
        self.failUnlessEqual(item.lastModification, pim.Modification.created)
        self.failUnless(item.userReminderTime is None)
        
        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)

    def testMovies(self):
        item = self.getItem(u"Movie list")
        self.checkStampness(item)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.later)
        self.failUnlessEqual(item.lastModification, pim.Modification.created)
        self.failUnless(item.userReminderTime is None)
        
        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in self.getCollection(u"Fun"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 3)

    def testBooks(self):
        item = self.getItem(u"Book list")
        self.checkStampness(item)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.later)
        self.failUnlessEqual(item.lastModification, pim.Modification.created)
        self.failUnless(item.userReminderTime is None)
        
        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in self.getCollection(u"Fun"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 3)

    def testTaxes(self):
        item = self.getItem(u"File taxes!")
        self.checkStampness(item, pim.EventStamp, pim.TaskStamp)
        self.failUnlessEqual(item.triageStatus, pim.TriageEnum.later)
        self.failUnlessEqual(item.lastModification, pim.Modification.created)

        self.failIf(item.userReminderTime is None)
        self.failUnless(pim.EventStamp(item).userReminderInterval is None)
        
        self.failIf(pim.EventStamp(item).allDay)
        self.failUnless(pim.EventStamp(item).anyTime)

        self.failUnless(item in self.getCollection(u"Home"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)

    def testSoundExhibit(self):
        item = self.getItem(u"Class Trip: Exhibit on Sound!")
        self.checkStampness(item, pim.EventStamp)

        self.failUnless(pim.EventStamp(item).anyTime)
        self.failIf(pim.EventStamp(item).allDay)
        self.failUnlessEqual(
            pim.EventStamp(item).effectiveStartTime.date().weekday(),
            6
        )
        self.failUnless(pim.EventStamp(item).location is not None)
         
        self.failUnless(item.userReminderTime is None)
        self.failUnless(item in self.getCollection(u"Fun"))
        self.failUnless(item in schema.ns("osaf.pim", self.view).allCollection)
        self.failUnlessEqual(len(list(item.appearsIn)), 2)

    def testOrdering(self):
        def key(item):
            return (item._triageStatus, item._triageStatusChanged)

        items = sorted(schema.ns("osaf.pim", self.view).allCollection, key=key)
        
        displayNames = list(item.displayName for item in items
                            if pim.EventStamp(item).rruleset is None or
                               pim.EventStamp(item).occurrenceFor is not None)


        # Don't test exact item order, since the recurring events (plus
        # auto-triage) make the exact order complicated. Rather, check the
        # first few (non-recurring) items ...
        def failUnlessItemMatches(itemName, index):
            item = self.getItem(itemName)
            self.failUnlessEqual(displayNames[index], item.displayName)
            
        failUnlessItemMatches(u'Welcome to Chandler\u2122', 0)
        failUnlessItemMatches(u'Next dentist appointment?', 1)
        failUnlessItemMatches(u'Tell a friend about Chandler',  2)
        failUnlessItemMatches(u'Write-up...', 3)
        failUnlessItemMatches(u'Follow up with...on...', 4)
        failUnlessItemMatches(u'Start planning vacation', 5)

        # ... as well as the very last item
        failUnlessItemMatches(u'Download Chandler!', -1)
        

class SyncHolidaysTestCase(testcase.SingleRepositoryTestCase):
    """
    A test case for Bug 12158: It simulates what happens when
    we sync the U.S. Holidays collection from the server.
    """
    def testSync(self):
        def get():
            return pkg_resources.resource_string("osaf.app", "us_holidays.ics")
        holidays = findCollection(self.view, u"U.S. Holidays")
        share = sharing.SharedItem(holidays).shares.first()
        
        # Override get on the conduit so we can simulate getting
        # back exactly the same data from the server
        share.conduit.get = get
        share.sync()

        for item in holidays:
            self.failIf(not item.read, "Item %s is unread" % (item,))

if __name__ == "__main__":
    import unittest
    unittest.main()
        
