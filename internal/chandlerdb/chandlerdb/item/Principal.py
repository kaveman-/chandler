#   Copyright (c) 2004-2006 Open Source Applications Foundation
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


from chandlerdb.item.Item import Item


class Principal(Item):

    def isMemberOf(self, pid):
    
        if pid == self.itsUUID:
            return True

        principals = self._references.get('principals', None)
        if principals:

            if pid in principals:
                return True

            for principal in principals:
                if principal.isMemberOf(pid):
                    return True

        return False
