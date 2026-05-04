#!/usr/bin/perl
use strict;
use warnings;
use IO::Socket::INET;

$| = 1;  # autoflush stdout

my $MON_HOST  = '127.0.0.1';
my $MON_PORT  = 7100;
my $CONN_TO   = 10;   # connection timeout (seconds)
my $BANNER_TO = 5;    # banner read timeout (seconds)
my $CMD_DELAY = 0.1;  # delay between keystrokes (seconds)

sub fail {
    my ($msg) = @_;
    print STDERR "ERROR: $msg\n";
    exit 1;
}

# Connect to QEMU HMP monitor
my $sock = IO::Socket::INET->new(
    PeerHost => $MON_HOST,
    PeerPort => $MON_PORT,
    Proto    => 'tcp',
    Timeout  => $CONN_TO,
) or fail("Cannot connect to QEMU monitor at $MON_HOST:$MON_PORT ($!)");

$sock->autoflush(1);
print STDERR "Connected to QEMU monitor at $MON_HOST:$MON_PORT\n";

# Read banner (telnet negotiation)
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
    # Banner timeout is non-fatal — continue anyway
    print STDERR "Warning: did not receive QEMU banner within ${BANNER_TO}s\n";
}

# Add USB keyboard (no-op if already present)
print $sock "device_add usb-kbd\r\n";
print STDERR "Sent: device_add usb-kbd\n";

# Small delay to let QEMU process commands
select(undef, undef, undef, $CMD_DELAY);

# Open Start menu (Windows key)
print $sock "sendkey meta_l\r\n";
print STDERR "Sent: sendkey meta_l (Windows key)\n";
select(undef, undef, undef, 0.3);

# Type "sketchup" character by character
for my $c (split('', 'sketchup')) {
    print $sock "sendkey $c\r\n";
    select(undef, undef, undef, $CMD_DELAY);
}
print STDERR "Sent: 'sketchup' keystrokes\n";

# Press Enter
select(undef, undef, undef, 0.2);
print $sock "sendkey ret\r\n";
print STDERR "Sent: sendkey ret (Enter)\n";

close($sock);
print STDERR "QEMU monitor commands sent successfully\n";
print "OK\n";
exit 0;
