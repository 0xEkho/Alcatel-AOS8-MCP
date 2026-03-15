"""
SSH credential resolution for AOS8 OmniSwitch devices.

Supports global credentials with per-zone fallback.
Zone is determined from the second octet of 10.X.0.0/16 subnets:
  - Global credentials : AOS_GLOBAL_USERNAME / AOS_GLOBAL_PASSWORD
  - Zone credentials   : AOS_ZONE{X}_USERNAME / AOS_ZONE{X}_PASSWORD
                         where X is the second octet of the target IP
                         (only applies when the host is in a 10.X.0.0/16 subnet)

No exception is ever raised — missing credentials fall back to global values
(which may themselves be empty strings).
"""
import ipaddress
import logging
import os

logger = logging.getLogger(__name__)


def _get_zone(host: str) -> int | None:
    """Return the zone index (second octet) if *host* is in a 10.X.0.0/16 subnet.

    Args:
        host: IP address string of the target OmniSwitch.

    Returns:
        Integer second octet (1-255) if the host is a 10.X.*.* address,
        ``None`` otherwise or if *host* cannot be parsed.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        logger.debug("Cannot parse host as IP address for zone detection: %s", host)
        return None

    if not isinstance(ip, ipaddress.IPv4Address):
        return None

    octets = ip.packed  # bytes
    if octets[0] == 10:
        return octets[1]  # second octet → zone index

    return None


def get_credentials(host: str) -> tuple[str, str]:
    """Resolve SSH credentials for the given host.

    Resolution order:
    1. If the host is in a ``10.X.0.0/16`` subnet **and** zone-specific
       credentials are configured (``AOS_ZONE{X}_USERNAME`` /
       ``AOS_ZONE{X}_PASSWORD``), those are returned.
    2. Otherwise the global credentials (``AOS_GLOBAL_USERNAME`` /
       ``AOS_GLOBAL_PASSWORD``) are returned.

    In all cases the function returns a ``(username, password)`` tuple —
    values may be empty strings when the corresponding environment variables
    are not set. No exception is raised.

    Args:
        host: IP address or hostname of the target OmniSwitch.

    Returns:
        Tuple of ``(username, password)``.
    """
    global_user = os.getenv("AOS_GLOBAL_USERNAME", "")
    global_pass = os.getenv("AOS_GLOBAL_PASSWORD", "")

    zone = _get_zone(host)
    if zone is not None:
        zone_user = os.getenv(f"AOS_ZONE{zone}_USERNAME", "").strip()
        zone_pass = os.getenv(f"AOS_ZONE{zone}_PASSWORD", "").strip()

        if zone_user:
            logger.debug(
                "Using zone-%d credentials for host %s (AOS_ZONE%d_USERNAME)",
                zone,
                host,
                zone,
            )
            return zone_user, zone_pass

        logger.debug(
            "No zone-%d credentials configured for host %s — falling back to global",
            zone,
            host,
        )

    logger.debug("Using global credentials for host %s", host)
    return global_user, global_pass
