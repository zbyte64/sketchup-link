#!/usr/bin/perl
# launch_sketchup.pl — Launch SketchUp inside the Windows VM via QEMU HMP
# with agent-rdp keyboard fallback.
#
# Primary method: Connect to QEMU HMP monitor (127.0.0.1:7100), send
# Windows key + "sketchup" + Enter keystrokes.
#
# Fallback method: If HMP connection fails, uses agent-rdp keyboard commands
# to type "sketchup" via the Start menu.
#
# Usage:
#   launch_sketchup.pl                         # Try HMP, fallback to agent-rdp
#   launch_sketchup.pl --method hmp            # HMP only
#   launch_sketchup.pl --method agent-rdp      # agent-rdp only

use strict;
use warnings;
use IO::Socket::INET;

$| = 1;

my $MON_HOST  = '127.0.0.1';
my $MON_PORT  = 7100;
my $CONN_TO   = 10;
my $BANNER_TO = 5;
my $CMD_DELAY = 0.1;

my $METHOD = 'auto';  # auto, hmp, agent-rdp

# Parse args
while (@ARGV) {
    my $arg = shift @ARGV;
    if ($arg eq '--method' && @ARGV) {
        $METHOD = shift @ARGV;
    }
}

sub fail {
    my ($msg) = @_;
    print STDERR "ERROR: $msg\n";
    return 0;  # non-fatal for fallback
}

sub hmp_method {
    # Connect to QEMU HMP monitor
    my $sock = IO::Socket::INET->new(
        PeerHost => $MON_HOST,
        PeerPort => $MON_PORT,
        Proto    => 'tcp',
        Timeout  => $CONN_TO,
    );
    unless ($sock) {
        print STDERR "HMP method: Cannot connect to QEMU monitor ($!)\n";
        return 0;
    }

    $sock->autoflush(1);
    print STDERR "HMP method: Connected to QEMU monitor\n";

    # Read banner
    eval {
        local $SIG{ALRM} = sub { die "banner timeout\n" };
        alarm($BANNER_TO);
        while (<$sock>) {
            if (/\bqemu\b/i) {
                alarm(0);
                last;
            }
        }
    };
    if ($@) {
        print STDERR "HMP method: Warning — did not receive QEMU banner\n";
    }

    # Add USB keyboard (no-op if already present)
    print $sock "device_add usb-kbd\r\n";
    print STDERR "HMP method: Sent: device_add usb-kbd\n";
    select(undef, undef, undef, $CMD_DELAY);

    # Open Start menu
    print $sock "sendkey meta_l\r\n";
    print STDERR "HMP method: Sent: meta_l (Windows key)\n";
    select(undef, undef, undef, 0.3);

    # Type "sketchup" character by character
    for my $c (split('', 'sketchup')) {
        print $sock "sendkey $c\r\n";
        select(undef, undef, undef, $CMD_DELAY);
    }
    print STDERR "HMP method: Typed 'sketchup'\n";

    # Press Enter
    select(undef, undef, undef, 0.2);
    print $sock "sendkey ret\r\n";
    print STDERR "HMP method: Sent: ret (Enter)\n";

    close($sock);
    print STDERR "HMP method: Done\n";
    print "OK (HMP)\n";
    return 1;
}

sub agent_rdp_method {
    # Use agent-rdp keyboard commands as fallback
    print STDERR "agent-rdp method: Typing via keyboard...\n";

    # Check if agent-rdp is available
    my $rdp_check = `which agent-rdp 2>/dev/null || command -v agent-rdp 2>/dev/null`;
    chomp $rdp_check;
    unless ($rdp_check) {
        print STDERR "agent-rdp method: agent-rdp not found in PATH\n";
        return 0;
    }

    # Ensure session is connected
    my $session_check = `agent-rdp --session sketchup-link session info 2>/dev/null`;
    unless ($session_check =~ /connected/i) {
        print STDERR "agent-rdp method: Connecting session...\n";
        system('agent-rdp', '--session', 'sketchup-link', 'connect',
            '--host', '127.0.0.1', '-u', 'Docker', '-p', 'admin',
            '--enable-win-automation');
        sleep(3);
    }

    # Open Start menu
    print STDERR "agent-rdp method: Pressing Windows key...\n";
    system('agent-rdp', '--session', 'sketchup-link', 'keyboard', 'press', 'win');
    sleep(1);

    # Type "sketchup"
    print STDERR "agent-rdp method: Typing 'sketchup'...\n";
    system('agent-rdp', '--session', 'sketchup-link', 'keyboard', 'type', 'sketchup');
    sleep(2);

    # Press Enter
    print STDERR "agent-rdp method: Pressing Enter...\n";
    system('agent-rdp', '--session', 'sketchup-link', 'keyboard', 'press', 'enter');

    print STDERR "agent-rdp method: Done\n";
    print "OK (agent-rdp)\n";
    return 1;
}

# ============================================================
# Main
# ============================================================
print STDERR "Launching SketchUp (method: $METHOD)...\n";

if ($METHOD eq 'hmp') {
    exit hmp_method() ? 0 : 1;
} elsif ($METHOD eq 'agent-rdp') {
    exit agent_rdp_method() ? 0 : 1;
} else {
    # auto: try HMP first, fallback to agent-rdp
    if (hmp_method()) {
        exit 0;
    }
    print STDERR "HMP method failed — trying agent-rdp fallback...\n";
    sleep(1);
    if (agent_rdp_method()) {
        exit 0;
    }
    print STDERR "Both methods failed\n";
    exit 1;
}
