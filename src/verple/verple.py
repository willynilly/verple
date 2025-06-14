
import re

import semver
from packaging.version import Version as Pep440Version


class Verple:
    """
    Verple: Strict, conservative universal version comparator, serializer, and protocol.

    Design Criteria:
    -----------------
    1. Conservative equality semantics:
        - Versions are only equal if all fields match exactly:
            release, prerelease, postrelease, devrelease, local (build metadata).
            Any differences are treated as functionally distinct.

    2. Conservative ordering semantics:
        - Ordering only allowed when local/build metadata match.
        - Refuses ordering if ambiguity exists (raises ValueError).
        - Follows PEP 440 precedence model where applicable, with strict enforcement.

    3. Hashability:
        - Fully hashable and safe for use in sets and dictionaries.
        - __hash__ is consistent with __eq__.

    4. Canonical string serialization:
        - Provides reversible canonical string format via `to_canonical_string()`.
        - Fully parseable using regex with `from_canonical_string()`.

    5. JSON-LD serialization:
        - Full support for machine-readable semantic serialization via `to_jsonld()`.
        - JSON-LD includes explicit versioning of the serialization format ("verple").
        - Includes `sourceFormat` (which parser was used) and `sourceInput` (the original input string).

    6. Versioned deserialization protocol:
        - Deserialization uses the `verple` field to dispatch to correct loader.
        - Allows safe forward evolution of the data model while preserving backward compatibility.

    7. Multi-standard input support:
        - Can parse version strings from PEP 440, SemVer, Canonical, or CalVer formats.

    Use Case:
    ---------
    This design is highly suitable for:
      - Strict reproducible builds
      - Package registries
      - Deployment pipelines
      - Long-term archival systems
      - Build graph versioning
      - Scientific reproducibility and provenance tracking
    """

    VERPLE_VERSION: str = "1.0.0"
    VERPLE_CONTEXT: str = "https://gitlab.com/willynilly/verple/-/raw/main/src/verple/context/v1.0.0.jsonld"
    VERPLE_TYPE: str = "Verple"

    _SEMVER_TO_PEP440_PRERELEASE = {'alpha': 'a', 'beta': 'b', 'rc': 'rc'}

    CANONICAL_VERSION_REGEX = re.compile(r"""
        ^
        (?P<release>\d+(?:\.\d+){1,2})
        (?:-(?P<prerelease>[a-z]+[0-9]*))?
        (?:\.post(?P<post>[0-9]+))?
        (?:\.dev(?P<dev>[0-9]+))?
        (?:\+(?P<local>.+))?
        $
        """, re.VERBOSE)

    def __init__(self, release, prerelease=None, postrelease=None, devrelease=None, local=None, source_input=None, source_format=None):
        self.release = tuple(release)
        self.prerelease = prerelease
        self.postrelease = postrelease
        self.devrelease = devrelease
        self.local = local
        self.source_input = source_input
        self.source_format = source_format

    def __eq__(self, other):
        if not isinstance(other, Verple):
            return NotImplemented
        return (
            self.release == other.release and
            self.prerelease == other.prerelease and
            self.postrelease == other.postrelease and
            self.devrelease == other.devrelease and
            self.local == other.local
        )

    def __hash__(self):
        return hash((self.release, self.prerelease, self.postrelease, self.devrelease, self.local))

    def __lt__(self, other):
        if not isinstance(other, Verple):
            return NotImplemented
        if self.local != other.local:
            raise ValueError(f"Cannot confidently order versions with differing local metadata: {self} vs {other}")
        return self._ordering_tuple() < other._ordering_tuple()

    def _ordering_tuple(self):
        return (
            self.release,
            self._prerelease_key(self.prerelease),
            self.postrelease if self.postrelease is not None else -1,
            self.devrelease if self.devrelease is not None else float('inf'),
        )

    @staticmethod
    def _prerelease_key(prerelease):
        if prerelease is None:
            return (float('inf'),)
        label, num = prerelease
        return (label, num)

    def __repr__(self):
        return f"Verple('{self.source_input}')"

    def to_canonical_string(self):
        parts = [".".join(map(str, self.release))]
        if self.prerelease:
            label, num = self.prerelease
            parts[-1] += f"-{label}{num}"
        if self.postrelease is not None:
            parts.append(f"post{self.postrelease}")
        if self.devrelease is not None:
            parts.append(f"dev{self.devrelease}")
        canonical = ".".join(parts)
        if self.local:
            canonical += f"+{self.local}"
        return canonical

    def to_jsonld(self):
        return {
            "@context": self.VERPLE_CONTEXT,
            "@type": self.VERPLE_TYPE,
            "verple": self.VERPLE_VERSION,
            "sourceFormat": self.source_format,
            "sourceInput": self.source_input,
            "release": list(self.release),
            "prerelease": list(self.prerelease) if self.prerelease else None,
            "postrelease": self.postrelease,
            "devrelease": self.devrelease,
            "local": self.local
        }

    @staticmethod
    def from_jsonld(data):
        version = data.get("verple")
        if version == "1.0.0":
            return Verple._from_jsonld_v1_0_0(data)
        else:
            raise ValueError(f"Unsupported verple version: {version}")

    @staticmethod
    def _from_jsonld_v1_0_0(data):
        release = tuple(data["release"])
        prerelease = tuple(data["prerelease"]) if data.get("prerelease") else None
        postrelease = data.get("postrelease")
        devrelease = data.get("devrelease")
        local = data.get("local")
        source_input = data.get("sourceInput")
        source_format = data.get("sourceFormat")
        return Verple(release, prerelease, postrelease, devrelease, local, source_input, source_format)

    @staticmethod
    def from_canonical_string(version_string):
        match = Verple.CANONICAL_VERSION_REGEX.match(version_string)
        if not match:
            raise ValueError(f"Invalid canonical version: {version_string}")

        release = tuple(map(int, match.group("release").split(".")))
        prerelease = None
        if match.group("prerelease"):
            m = re.match(r"([a-z]+)(\d*)", match.group("prerelease"))
            if m:
                label, num = m.group(1), int(m.group(2)) if m.group(2) else 0
                prerelease = (label, num)
        postrelease = int(match.group("post")) if match.group("post") else None
        devrelease = int(match.group("dev")) if match.group("dev") else None
        local = match.group("local") or None
        return Verple(release, prerelease, postrelease, devrelease, local, source_input=version_string, source_format="canonical")

    @staticmethod
    def from_pep_440(version_string):
        try:
            v = Pep440Version(version_string)
        except Exception as e:
            raise ValueError(f"Invalid PEP 440 version: {version_string}") from e

        prerelease = v.pre if v.pre else None
        postrelease = v.post if v.post else None
        devrelease = v.dev if v.dev else None
        local = v.local if v.local else None

        return Verple(v.release, prerelease, postrelease, devrelease, local, source_input=version_string, source_format="pep440")

    @staticmethod
    def from_sem_ver(version_string):
        try:
            sv = semver.Version.parse(version_string)
        except ValueError as e:
            raise ValueError(f"Invalid SemVer: {version_string}") from e

        release = (sv.major, sv.minor, sv.patch)

        prerelease = None
        if sv.prerelease:
            prerelease_parts = sv.prerelease.split('.')
            label = prerelease_parts[0].lower()
            pep_label = Verple._SEMVER_TO_PEP440_PRERELEASE.get(label, label)
            num = int(prerelease_parts[1]) if len(prerelease_parts) > 1 and prerelease_parts[1].isdigit() else 0
            prerelease = (pep_label, num)

        local = sv.build if sv.build else None

        return Verple(release, prerelease, None, None, local, source_input=version_string, source_format="semver")

    @staticmethod
    def from_cal_ver(version_string):
        try:
            parts = tuple(int(part) for part in version_string.split("."))
            if not parts or any(part < 0 for part in parts):
                raise ValueError
            return Verple(parts, None, None, None, None, source_input=version_string, source_format="calver")
        except Exception:
            raise ValueError(f"Invalid CalVer: {version_string}")

    @staticmethod
    def parse(version_string):
        try:
            return Verple.from_pep_440(version_string)
        except ValueError:
            try:
                return Verple.from_sem_ver(version_string)
            except ValueError:
                try:
                    return Verple.from_canonical_string(version_string)
                except ValueError:
                    return Verple.from_cal_ver(version_string)
