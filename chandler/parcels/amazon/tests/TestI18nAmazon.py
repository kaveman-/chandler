# -*- coding: utf-8 -*-
__revision__  = "$Revision: 7664 $"
__date__      = "$Date: 2005-10-06 10:07:33 -1000 (Thu, 06 Oct 2005) $"
__copyright__ = "Copyright (c) 2004 Open Source Applications Foundation"
__license__   = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

""" Unit test for amazon i18n I/O """

import unittest
from osaf.pim.tests import TestContentModel
from amazon import AmazonKinds
import os

#XXX: The unit test has been disabled for tinderbox builds till
#     a mock server can be put in place.
#     The test can fail on the Amazon server side
#     which can lead to false positives.
#     The test will still run using the run_tests framework
if False:
    class TestI18nAmazon(TestContentModel.ContentModelTestCase):
    
        def setUp(self):
            super(TestI18nAmazon, self)._setup(self)
    
            self.testdir = os.path.join(self.rootdir, 'parcels', 'amazon')
    
            super(TestI18nAmazon, self)._openRepository(self)
            self.loadParcel("amazon")
            self.view = self.rep.view
    
    
        def testI18nSearch(self):
            if not self.isOnline():
                return
    
            #Try and retrieve a keyword which is not valid. This tests that the
            #parcel correctly handles the case when data is not returned
            col = AmazonKinds.SearchByKeyword(self.view, self.view, u'sdsdsdasdasdasdsDFDSFSDFsdasd', 'us', 'music')
            self.assertEquals(col, None)
    
            #Test that the Japanese product name is returned by an amazon search for
            #keyword 'Rap' in the Music category of amazon.co.jp
            productName = u'RAPâ€•ã�“ã‚Œã�§ãƒ©ãƒƒãƒ—ãƒ»ãƒŸãƒ¥ãƒ¼ã‚¸ãƒƒã‚¯ã�Œã‚�ã�‹ã‚‹'
            col = AmazonKinds.SearchByKeyword(self.view, self.view, 'Rap', 'jp', 'music')
            self.assertNotEquals(col, None)
            self.assertTrue(self.hasKey(col, productName))
    
            #Test that the German product name is return by an amazon search for
            #keyword == productName in the Music category of amazon.de
            productName = u'Im ZauberschloÃŸ... Auf dem Weg zum Schlafen und TrÃ¤umen'
            col = AmazonKinds.SearchByKeyword(self.view, self.view, 'Zauberschloss', 'de', 'music')
            self.assertNotEquals(col, None)
            self.assertTrue(self.hasKey(col, productName))
    
    
        def testI18nEmail(self):
            if not self.isOnline():
                return
    
            #A wishlist for bkirsch@osafoundation.org on amazon.com contains theses
            #four non-ascii product names. Retrieve the list from amazon.com and confirm
            #that these titles are in the list
            productNames = [
                            u"Die Ãœbungspatrone: HÃ¶rspiele (Literatur heute)",
                            u"FrÃ¼he sozialistische HÃ¶rspiele",
                            u"El lÃ¡piz del carpintero (Punto de Lectura)",
                            u"Cien AÃ±os de Soledad"
                           ]
    
            col = AmazonKinds.SearchWishListByEmail(self.view, self.view, \
                                                     'bkirsch@osafoundation.org', 'us')
    
            self.assertNotEquals(col, None)
    
            for productName in productNames:
                self.assertTrue(self.hasKey(col, productName))
    
            #This email address does not have an amazon.com wishlist. This tests
            #that the parcel correctly handles the case when data is not returned
            col = AmazonKinds.SearchWishListByEmail(self.view, self.view, \
                                                     'fake_address@osafoundation.org', 'us')
    
            self.assertEquals(col, None)
    
    
        def hasKey(self, col, key):
            if col is None:
                return False
    
            for item in col:
                if item.getItemDisplayName() == key:
                    return True
            return False


if __name__ == "__main__":
    unittest.main()
 