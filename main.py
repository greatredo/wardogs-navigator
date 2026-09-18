import sys
from wardogs_nav.app import run

if __name__=='__main__':
    if len(sys.argv)>2 and sys.argv[1]=='--self-test':
        from wardogs_nav.diagnostics import run_selftest
        sys.exit(run_selftest(sys.argv[2]))
    sys.exit(run())
