# Bahrain areas (towns and districts) grouped by governorate, used by rooms.
# Keys must match DISTRICTS in districts.py.
#
# Compiled from Wikipedia (Governorates of Bahrain, the four governorate pages
# and the individual town pages) and citypopulation.de. Towns whose governorate
# differs between sources (e.g. Jidhafs) are left out until checked against the
# official list from the Survey and Land Registration Bureau.
AREAS_BY_DISTRICT = {
    "capital": (
        "Manama",
        "Adliya",
        "Diplomatic Area",
        "Gudaibiya",
        "Hoora",
        "Jid Ali",
        "Juffair",
        "Ras Rumman",
        "Sanabis",
        "Sanad",
        "Seef",
        "Sitra",
        "Tubli",
        "Zinj",
        "Jidhafs",
    ),
    "muharraq": (
        "Muharraq",
        "Al Dair",
        "Al Hidd",
        "Amwaj Islands",
        "Arad",
        "Busaiteen",
        "Diyar Al Muharraq",
        "Galali",
        "Halat Bu Maher",
        "Samaheej",
    ),
    "northern": (
        "A'ali",
        "Abu Saiba",
        "Al Hajar",
        "Al Markh",
        "Al Qadam",
        "Al Qala",
        "Barbar",
        "Boori",
        "Budaiya",
        "Buquwa",
        "Dar Kulaib",
        "Diraz",
        "Dumistan",
        "Hamad Town",
        "Hamala",
        "Hillat Abdul Saleh",
        "Janabiya",
        "Jannusan",
        "Jasra",
        "Jid Al-Haj",
        "Karrana",
        "Karzakan",
        "Malikiya",
        "Muqaba",
        "North Sehla",
        "Northern City",
        "Qurayya",
        "Saar",
        "Sadad",
        "Salmabad",
        "Shahrakan",
        "Shakhura",
        "Umm an Nasan",
        "Umm as Sabaan",
        "Zayed City",
    ),
    "southern": (
        "Riffa",
        "Al Dur",
        "Askar",
        "Awali",
        "Durrat Al Bahrain",
        "Hawar Islands",
        "Isa Town",
        "Jaww",
        "Khalifa City",
        "Ma'ameer",
        "Sakhir",
        "Zallaq",
    ),
}


def is_area_in_district(area: str, district: str) -> bool:
    """True if the area belongs to the district (exact match, case sensitive)"""
    return area in AREAS_BY_DISTRICT.get(district, ())
