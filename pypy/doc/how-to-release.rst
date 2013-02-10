
Making a PyPy Release
=======================

Overview
---------

As a meta rule setting up issues in the tracker for items here may help not
forgetting things. A set of todo files may also work.

Check and prioritize all issues for the release, postpone some if necessary,
create new  issues also as necessary. An important thing is to get
the documentation into an up-to-date state!

Release Steps
----------------

* at code freeze make a release branch using release-x.x.x in mercurial
  IMPORTANT: bump the
  pypy version number in module/sys/version.py and in
  module/cpyext/include/patchlevel.h, notice that the branch
  will capture the revision number of this change for the release;
  some of the next updates may be done before or after branching; make
  sure things are ported back to the trunk and to the branch as
  necessary
* update pypy/doc/contributor.rst (and possibly LICENSE)
* rename pypy/doc/whatsnew_head.rst to whatsnew_VERSION.rst
  and create a fresh whatsnew_head.rst after the release
* update README
* change the tracker to have a new release tag to file bugs against
* go to pypy/tool/release and run:
  force-builds.py /release/<release branch>
* wait for builds to complete, make sure there are no failures
* run pypy/tool/release/make_release.py, this will build necessary binaries
  and upload them to pypy.org

  Following binaries should be built, however, we need more buildbots:
    JIT: windows, linux, os/x
    no JIT: windows, linux, os/x
    sandbox: linux, os/x

* write release announcement pypy/doc/release-x.y(.z).txt
  the release announcement should contain a direct link to the download page
* update pypy.org (under extradoc/pypy.org), rebuild and commit

* post announcement on morepypy.blogspot.com
* send announcements to pypy-dev, python-list,
  python-announce, python-dev ...
