# See the file LICENSE for redistribution information.
#
# Copyright (c) 1999,2007 Oracle.  All rights reserved.
#
# $Id: test081.tcl,v 12.5 2007/05/17 15:15:56 bostic Exp $
#
# TEST	test081
# TEST	Test off-page duplicates and overflow pages together with
# TEST	very large keys (key/data as file contents).
proc test081 { method {ndups 13} {tnum "081"} args} {
	source ./include.tcl

	eval {test017 $method 1 $ndups $tnum} $args
}
