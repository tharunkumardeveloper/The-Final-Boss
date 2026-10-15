"""Generate the company's worldwide catalogue -> data/kb_world.json.

The company is fictional; everything about the company is generated here. Real place names come from GeoNames
(cities15000, CC BY 4.0, https://www.geonames.org): cities, their nearby towns as service areas, and spelling
aliases. About 25 major cities also get hand-picked neighbourhoods (GeoNames has no neighbourhoods).

Run: python -m data.kb_world   (needs data/geonames/cities15000.txt and countryInfo.txt; see README)
"""
import json
import sys
import math
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
GEO = HERE / "geonames"

# region code -> (tenant graph, display name, backbones [(id, label, city)])
REGIONS = {
    "in":    ("pml",       "India",                [("core-west", "Core West", "mumbai"), ("core-south", "Core South", "hyderabad"), ("core-north", "Core North", "delhi")]),
    "eu":    ("pml-eu",    "Europe",               [("core-fra", "Core Frankfurt", "frankfurt am main"), ("core-ams", "Core Amsterdam", "amsterdam"), ("core-lon", "Core London", "london")]),
    "na":    ("pml-na",    "North America",        [("core-nyc", "Core New York", "new york city"), ("core-dal", "Core Dallas", "dallas"), ("core-tor", "Core Toronto", "toronto")]),
    "apac":  ("pml-apac",  "Asia-Pacific",         [("core-sin", "Core Singapore", "singapore"), ("core-tyo", "Core Tokyo", "tokyo"), ("core-syd", "Core Sydney", "sydney")]),
    "mea":   ("pml-mea",   "Middle East & Africa", [("core-dxb", "Core Dubai", "dubai"), ("core-jnb", "Core Johannesburg", "johannesburg")]),
    "latam": ("pml-latam", "Latin America",        [("core-sao", "Core Sao Paulo", "sao paulo"), ("core-bog", "Core Bogota", "bogota")]),
}

# iso -> (region, cities to serve, local currency units per USD, price level vs US, sales tax name, %, payment methods)
COUNTRIES = {
    "IN": ("in", 14, 84, 0.22, "GST", 18, ["UPI", "credit or debit card", "netbanking", "wallets"]),
    "GB": ("eu", 8, 0.78, 0.95, "VAT", 20, ["card", "Direct Debit", "PayPal"]),
    "DE": ("eu", 8, 0.92, 0.9, "MwSt", 19, ["SEPA direct debit", "card", "PayPal"]),
    "FR": ("eu", 7, 0.92, 0.9, "TVA", 20, ["SEPA direct debit", "carte bancaire", "PayPal"]),
    "ES": ("eu", 6, 0.92, 0.75, "IVA", 21, ["SEPA direct debit", "card", "Bizum"]),
    "IT": ("eu", 6, 0.92, 0.8, "IVA", 22, ["SEPA direct debit", "card", "PayPal"]),
    "NL": ("eu", 5, 0.92, 0.95, "BTW", 21, ["iDEAL", "SEPA direct debit", "card"]),
    "SE": ("eu", 4, 10.6, 0.95, "moms", 25, ["autogiro", "card", "Swish"]),
    "PL": ("eu", 5, 4.0, 0.55, "VAT", 23, ["BLIK", "card", "bank transfer"]),
    "IE": ("eu", 3, 0.92, 1.0, "VAT", 23, ["SEPA direct debit", "card"]),
    "PT": ("eu", 3, 0.92, 0.7, "IVA", 23, ["MB Way", "SEPA direct debit", "card"]),
    "BE": ("eu", 3, 0.92, 0.9, "TVA/BTW", 21, ["Bancontact", "SEPA direct debit", "card"]),
    "AT": ("eu", 3, 0.92, 0.9, "USt", 20, ["SEPA direct debit", "card"]),
    "CH": ("eu", 3, 0.88, 1.3, "MWST", 8.1, ["TWINT", "card", "LSV"]),
    "DK": ("eu", 3, 6.9, 1.0, "moms", 25, ["MobilePay", "Betalingsservice", "card"]),
    "FI": ("eu", 3, 0.92, 0.95, "ALV", 25.5, ["e-invoice", "card"]),
    "US": ("na", 14, 1.0, 1.0, "sales tax", 0, ["card", "ACH bank transfer", "PayPal"]),
    "CA": ("na", 7, 1.37, 0.9, "GST/HST", 13, ["pre-authorized debit", "card", "Interac"]),
    "MX": ("na", 6, 17.5, 0.45, "IVA", 16, ["card", "OXXO", "SPEI transfer"]),
    "SG": ("apac", 1, 1.35, 0.9, "GST", 9, ["PayNow", "GIRO", "card"]),
    "JP": ("apac", 8, 150, 0.75, "consumption tax", 10, ["card", "konbini", "bank transfer"]),
    "AU": ("apac", 7, 1.52, 0.95, "GST", 10, ["direct debit", "card", "BPAY"]),
    "NZ": ("apac", 3, 1.65, 0.9, "GST", 15, ["direct debit", "card"]),
    "ID": ("apac", 6, 15700, 0.3, "PPN", 11, ["GoPay", "OVO", "virtual account"]),
    "MY": ("apac", 4, 4.6, 0.4, "SST", 8, ["DuitNow", "FPX", "card"]),
    "PH": ("apac", 5, 56, 0.35, "VAT", 12, ["GCash", "Maya", "card"]),
    "TH": ("apac", 4, 35, 0.4, "VAT", 7, ["PromptPay", "card"]),
    "VN": ("apac", 4, 24500, 0.3, "VAT", 10, ["MoMo", "VNPay", "card"]),
    "KR": ("apac", 5, 1350, 0.7, "VAT", 10, ["KakaoPay", "card", "bank transfer"]),
    "AE": ("mea", 3, 3.67, 1.0, "VAT", 5, ["card", "Apple Pay", "bank transfer"]),
    "SA": ("mea", 4, 3.75, 0.85, "VAT", 15, ["mada", "STC Pay", "card"]),
    "ZA": ("mea", 5, 18.5, 0.4, "VAT", 15, ["debit order", "card", "EFT"]),
    "NG": ("mea", 4, 1500, 0.25, "VAT", 7.5, ["card", "bank transfer", "USSD"]),
    "KE": ("mea", 3, 130, 0.3, "VAT", 16, ["M-Pesa", "card"]),
    "EG": ("mea", 3, 48, 0.25, "VAT", 14, ["Fawry", "card", "Vodafone Cash"]),
    "BR": ("latam", 8, 5.0, 0.45, "ICMS", 0, ["Pix", "boleto", "card"]),
    "AR": ("latam", 4, 900, 0.35, "IVA", 21, ["Mercado Pago", "card", "debito automatico"]),
    "CL": ("latam", 3, 930, 0.55, "IVA", 19, ["Webpay", "card"]),
    "CO": ("latam", 4, 4000, 0.35, "IVA", 19, ["PSE", "Nequi", "card"]),
}

# Hand-picked neighbourhoods (GeoNames has none) and common short names, keyed by GeoNames ASCII city name.
NEIGHBOURHOODS = {
    "Pune": ["Baner", "Kothrud", "Viman Nagar", "Hinjewadi", "Koregaon Park", "Wakad", "Hadapsar", "Aundh"],
    "Mumbai": ["Andheri", "Bandra", "Powai", "Thane", "Colaba", "Malad", "Chembur", "Borivali"],
    "Bengaluru": ["Koramangala", "Whitefield", "Indiranagar", "HSR Layout", "Jayanagar", "Electronic City", "Hebbal", "Marathahalli"],
    "Hyderabad": ["Gachibowli", "Madhapur", "Kondapur", "Banjara Hills", "Jubilee Hills", "Kukatpally", "Secunderabad", "Begumpet"],
    "Chennai": ["T. Nagar", "Adyar", "Velachery", "Anna Nagar", "OMR", "Tambaram", "Porur", "Mylapore"],
    "Delhi": ["Connaught Place", "Saket", "Dwarka", "Vasant Kunj", "Lajpat Nagar", "Rohini", "Karol Bagh"],
    "Kolkata": ["Salt Lake", "Park Street", "New Town", "Ballygunge", "Howrah", "Behala"],
    "London": ["Camden", "Islington", "Hackney", "Shoreditch", "Croydon", "Wimbledon", "Greenwich", "Canary Wharf"],
    "Paris": ["Montmartre", "Le Marais", "La Defense", "Belleville", "Bastille", "Saint-Germain"],
    "Berlin": ["Kreuzberg", "Mitte", "Prenzlauer Berg", "Neukolln", "Charlottenburg", "Friedrichshain"],
    "Amsterdam": ["Jordaan", "De Pijp", "Amsterdam-Noord", "Oud-West", "Zuidas"],
    "Madrid": ["Salamanca", "Chamberi", "Malasana", "Retiro", "Chamartin"],
    "New York City": ["Manhattan", "Brooklyn", "Queens", "The Bronx", "Staten Island", "Harlem", "Williamsburg"],
    "San Francisco": ["Mission District", "SoMa", "Sunset District", "Nob Hill", "Castro"],
    "Los Angeles": ["Hollywood", "Santa Monica", "Downtown LA", "Silver Lake", "Venice", "Koreatown"],
    "Chicago": ["The Loop", "Lincoln Park", "Wicker Park", "Hyde Park", "Logan Square"],
    "Toronto": ["Downtown Toronto", "Scarborough", "North York", "Etobicoke", "The Annex"],
    "Singapore": ["Orchard", "Tampines", "Jurong East", "Woodlands", "Bukit Timah", "Punggol", "Marina Bay"],
    "Tokyo": ["Shibuya", "Shinjuku", "Minato", "Setagaya", "Meguro", "Koto"],
    "Sydney": ["Bondi", "Parramatta", "Surry Hills", "Chatswood", "Newtown", "Manly"],
    "Dubai": ["Dubai Marina", "Downtown Dubai", "Jumeirah", "Deira", "Business Bay", "JLT"],
    "Johannesburg": ["Sandton", "Rosebank", "Soweto", "Randburg", "Braamfontein"],
    "Sao Paulo": ["Pinheiros", "Moema", "Vila Madalena", "Itaim Bibi", "Bela Vista"],
    "Mexico City": ["Polanco", "Condesa", "Roma", "Coyoacan", "Santa Fe"],
    "Seoul": ["Gangnam", "Hongdae", "Itaewon", "Jamsil", "Yeouido"],
}
EXTRA_ALIASES = {"Bengaluru": ["blr", "bangalore", "bengalooru"], "Mumbai": ["bombay", "bom"], "Chennai": ["madras"],
                 "Delhi": ["new delhi", "ncr"], "Kolkata": ["calcutta"], "New York City": ["nyc", "new york", "ny"],
                 "Los Angeles": ["la"], "San Francisco": ["sf", "san fran"], "London": ["ldn"], "Sao Paulo": ["sampa"],
                 "Hyderabad": ["hyd"], "Pune": ["poona"], "Nice": ["nice france"], "Cork": ["cork ireland"]}

ROUTERS = [{"key": "pml hub 6", "name": "PML Hub 6", "wifi": "Wi-Fi 6, dual band", "ports": "4 gigabit LAN", "range_sqm": 140},
           {"key": "pml hub 6 pro", "name": "PML Hub 6 Pro", "wifi": "Wi-Fi 6E, tri band", "ports": "4 gigabit LAN + 1 2.5G", "range_sqm": 200},
           {"key": "pml hub 7", "name": "PML Hub 7", "wifi": "Wi-Fi 7, tri band", "ports": "4 x 2.5G LAN + 10G WAN", "range_sqm": 260}]

# Base prices in USD at US price level; local price = base * price level * fx, rounded to a friendly number.
PLANS = [
    {"key": "fiber 100", "name": "Fiber 100", "down": 100, "up": 50, "devices": 10, "router": "pml hub 6", "usd": 35, "lock_in": 0,
     "install_usd": 0, "includes": ["free installation", "PML Hub 6 router"], "good_for": "1-3 people: HD streaming, video calls, browsing"},
    {"key": "fiber 300", "name": "Fiber 300", "down": 300, "up": 150, "devices": 25, "router": "pml hub 6", "usd": 50, "lock_in": 0,
     "install_usd": 0, "includes": ["free installation", "PML Hub 6 router", "OTT bundle for 3 months"],
     "good_for": "families: 4K streaming, gaming, working from home"},
    {"key": "fiber 1000", "name": "Fiber 1000", "down": 1000, "up": 500, "devices": 60, "router": "pml hub 6 pro", "usd": 75, "lock_in": 0,
     "install_usd": 0, "includes": ["free installation", "PML Hub 6 Pro router", "OTT bundle", "priority support"],
     "good_for": "heavy users: creators, big households, home offices with large uploads"},
    {"key": "fiber 2 gig", "name": "Fiber 2 Gig", "down": 2000, "up": 1000, "devices": 120, "router": "pml hub 7", "usd": 110, "lock_in": 12,
     "install_usd": 0, "includes": ["free installation", "PML Hub 7 router", "mesh extender", "static IP", "priority support"],
     "good_for": "power users and small studios", "regions": ["eu", "na", "apac"]},
    {"key": "business 500", "name": "Business 500", "down": 500, "up": 500, "devices": 80, "router": "pml hub 6 pro", "usd": 95, "lock_in": 12,
     "install_usd": 50, "includes": ["static IP", "4-hour fault response", "PML Hub 6 Pro router"],
     "good_for": "small offices and shops"},
]
ADDONS = [
    ("static ip", "Static IP", 6, "One fixed public IPv4 address, for hosting, remote access or CCTV."),
    ("mesh extender", "Mesh extender", 4, "Rented per month; covers dead zones in larger homes, up to 2 per home."),
    ("ott bundle", "OTT bundle", 6, "Three streaming apps on one bill; free for 3 months on Fiber 300 and above."),
    ("gaming boost", "Gaming Boost", 4, "Low-latency routing to major game servers and a priority queue at peak hours."),
    ("parental controls", "Family Shield", 2, "Content filters, schedules and pause-the-internet per device."),
    ("backup 4g", "Backup 4G", 5, "A 4G dongle that takes over automatically if the fiber line goes down."),
    ("smart home security", "Smart Home Security", 3, "Network-level protection for cameras, plugs and other smart devices."),
]
SERVICES = [
    ("new connection", "New connection", 0, "48 hours", "Free installation on every plan; a technician visits once."),
    ("relocation", "Shift my connection", 12, "2-3 working days", "Free once a year within the same city. Another country means a new connection there."),
    ("router replacement", "Router replacement", 0, "next working day", "Free if the router is faulty; charged at cost if damaged."),
    ("plan change", "Upgrade or downgrade", 0, "within 1 hour", "Upgrades are instant and billed pro-rata; downgrades apply from the next billing cycle."),
    ("technician visit", "Technician visit", 10, "same or next day", "Free when the fault is on our side; charged when the issue is inside the home wiring."),
    ("speed boost day", "Speed boost day pass", 3, "instant", "Your next tier for 24 hours, for big downloads or game launches."),
    ("vacation pause", "Vacation pause", 0, "from your chosen date", "Pause service for 15-90 days once a year; no monthly charge while paused."),
    ("cancellation", "Cancel service", 0, "end of billing cycle", "No fee without a lock-in; return the router within 15 days."),
    ("ownership transfer", "Transfer ownership", 0, "1 working day", "Move the connection to a family member or new tenant at the same address."),
    ("wifi checkup", "Home Wi-Fi checkup", 8, "next working day", "A technician maps coverage and places the router and extenders for best signal."),
]
POLICIES = [
    ("billing cycle", "Billing", "Bills are generated on the 1st and due by the 7th of each month."),
    ("late fee", "Late payment", "A small late fee applies after the due date; service pauses 15 days after it."),
    ("outage credit", "Outage credit", "If an outage on our side lasts over 24 hours, every affected day is credited automatically."),
    ("service level", "Service level", "We aim to fix faults within 24 hours, and to tell you about outages before you notice."),
    ("refunds", "Refunds", "Unused prepaid months are refunded within 7 working days if you cancel."),
    ("fair usage", "Fair usage", "All home plans are truly unlimited: no data caps and no speed throttling."),
    ("lock in", "Lock-in", "Home plans have no lock-in except Fiber 2 Gig (12 months). Business plans are 12 months."),
    ("equipment", "Equipment", "Routers and extenders stay ours; return them within 15 days of cancelling."),
    ("privacy", "Privacy", "We never sell customer data. Support conversations are kept to serve you and deleted 2 years after you leave."),
    ("data residency", "Where your data lives", "Customer data is stored in your region and never copied to another region's systems."),
    ("installation", "Installation", "A technician installs, tests speed with you, and leaves only when Wi-Fi works in your main rooms."),
    ("deposit", "Deposit", "No deposit on home plans; business plans need a one-month deposit."),
    ("price guarantee", "Price guarantee", "Your plan price stays the same for 12 months from activation."),
    ("accessibility", "Accessibility", "Large-print bills, screen-reader friendly portal, and phone support for anyone who prefers it."),
    ("student offer", "Student offer", "Students get 20% off Fiber 100 and Fiber 300 with a valid student ID."),
]
REGION_POLICY = {"eu": ("gdpr", "GDPR", "EU and UK customers can download or delete their data anytime; our DPO answers within 30 days."),
                 "na": ("net neutrality", "Open internet", "We don't block, throttle or prioritise lawful content."),
                 "in": ("trai", "TRAI compliance", "Plans, speeds and complaint handling follow TRAI rules; escalation to our appellate officer within 30 days."),
                 "apac": ("pdpa", "Personal data", "We follow local personal-data laws such as Singapore's PDPA and Australia's Privacy Act."),
                 "mea": ("local licence", "Licensing", "We operate under local telecom licences and keep customer data in-region."),
                 "latam": ("lgpd", "Personal data", "We follow local data-protection laws such as Brazil's LGPD.")}

ISSUES = [  # (issue key, steps): procedural memory the resolver follows, in order
    ("evening wifi drops", ["Check whether drops happen on wired devices too", "Move devices to the 5 GHz network", "Change the Wi-Fi channel to a less crowded one", "Update router firmware", "Add a mesh extender if the router is far away"]),
    ("slow speed", ["Run a speed test on a wired device", "Restart the router", "Check how many devices are streaming at once", "Upgrade the plan if usage outgrew it"]),
    ("no internet", ["Check the outage map for your area", "Check that the router's PON light is solid", "Reseat the fiber patch cable", "Restart the router", "Book a technician visit"]),
    ("router keeps rebooting", ["Check the power adapter is the original one", "Move the router somewhere ventilated", "Update router firmware", "Replace the router"]),
    ("high ping in games", ["Use a wired connection for the console", "Turn on Gaming Boost", "Close background downloads", "Pick the nearest game server region"]),
    ("buffering on tv", ["Check the TV is on 5 GHz", "Lower other heavy usage during streaming", "Restart the streaming app and TV", "Add a mesh extender near the TV"]),
    ("dns errors", ["Restart the router", "Switch DNS to automatic", "Flush DNS on the device", "Set DNS to 1.1.1.1 as a test"]),
    ("cannot connect to 5ghz", ["Check the device supports 5 GHz", "Move closer to the router", "Turn band steering off and on", "Update the device's Wi-Fi driver"]),
    ("weak signal in some rooms", ["Move the router to a central, raised spot", "Keep it away from mirrors and microwaves", "Add a mesh extender", "Book a Home Wi-Fi checkup"]),
    ("upload is slow", ["Test upload on a wired device", "Pause cloud backups during calls", "Check the plan's upload speed", "Upgrade to a plan with higher upload"]),
    ("vpn is slow", ["Try a closer VPN server", "Switch the VPN protocol", "Test speed with the VPN off to compare", "Ask your employer about split tunnelling"]),
    ("smart tv cannot connect", ["Forget the network and reconnect", "Check the Wi-Fi password", "Turn on 2.4 GHz compatibility mode", "Update the TV software"]),
    ("too many devices", ["List connected devices in the app", "Remove devices you don't use", "Add a mesh extender", "Upgrade to a plan built for more devices"]),
    ("red light on router", ["Check the outage map for your area", "Reseat the fiber cable", "Restart the router", "Book a technician visit"]),
    ("wired port not working", ["Try another cable", "Try another LAN port", "Restart the router", "Replace the router"]),
    ("video calls freeze", ["Use 5 GHz or a cable", "Close other video streams", "Turn on Gaming Boost for low latency", "Check upload speed"]),
    ("connection drops when it rains", ["Check the outdoor fiber box is sealed", "Report it so a technician checks the line", "Use Backup 4G until it's fixed"]),
    ("forgot wifi password", ["Read it from the router's label", "Change it in the {company} app", "Reconnect devices with the new password"]),
    ("billing amount looks wrong", ["Check for a pro-rata upgrade charge", "Check add-ons on the bill", "Check outage credits were applied", "Raise a billing ticket"]),
    ("payment failed", ["Check card or bank limits", "Try another payment method", "Pay before the late-fee date", "Set up auto-pay"]),
    ("new device not connecting", ["Restart the device", "Forget and rejoin the network", "Check the device limit on your plan", "Update the device"]),
    ("cctv cannot be viewed remotely", ["Add a Static IP", "Forward the camera port in the app", "Check the camera's firmware"]),
    ("speed drops at night", ["Check for neighbourhood congestion on the status page", "Use 5 GHz", "Turn on Gaming Boost", "Report it if it lasts over 3 nights"]),
    ("streaming apps blocked", ["Check Family Shield filters", "Restart the router", "Clear the app cache"]),
    ("mesh extender offline", ["Move it halfway between router and dead zone", "Restart the extender", "Re-pair it in the app", "Replace the extender"]),
]

FAQ_GENERAL = [
    ("how to buy", "How do I get {company}?", "Pick a plan on our site or tell us in chat, share your address, choose an installation slot, then pay the first month. A technician installs within 48 hours."),
    ("mobile use", "Can I use it on my phone?", "{company} is home fiber, not a SIM. Your phone connects to the home Wi-Fi like any other device; the app lets you manage it on the go."),
    ("router included", "Is a router included?", "Yes, every plan includes a router at no extra cost; the model depends on the plan."),
    ("own router", "Can I use my own router?", "Yes. Keep ours as the fiber gateway and put yours behind it, or ask us for bridge mode."),
    ("installation time", "How long does installation take?", "Usually 48 hours from order to a working connection; the visit itself takes about an hour."),
    ("contract", "Is there a contract?", "Home plans have no lock-in, except Fiber 2 Gig with 12 months. Business plans are 12 months."),
    ("data cap", "Is there a data limit?", "No. All plans are unlimited with no throttling."),
    ("ipv6", "Do you support IPv6?", "Yes, every connection has IPv4 and IPv6."),
    ("speed guarantee", "Will I get the full speed?", "Wired speed tests should reach the plan speed; Wi-Fi depends on distance, walls and the device."),
    ("outage notice", "How do I hear about outages?", "We message you as soon as our network team sees a fault that affects your line, usually before you notice."),
    ("support hours", "When can I reach support?", "Chat and WhatsApp-style messaging 24x7; phone support from 8 am to 10 pm local time."),
    ("multiple homes", "Can I have connections at two homes?", "Yes, each address is a separate connection on the same account."),
    ("moving abroad", "I'm moving to another country. Can I keep my plan?", "If we serve that country, we set up a new connection there and close the old one with no fee."),
    ("upgrade later", "Can I upgrade later?", "Anytime. Upgrades are instant and billed pro-rata."),
    ("pause", "Can I pause while travelling?", "Yes, the vacation pause stops billing for 15-90 days once a year."),
    ("refer friend", "Do you have referrals?", "Yes, you and your friend each get one month free after their installation."),
    ("business", "Do you offer business plans?", "Yes, Business 500 has symmetrical speed, a static IP and 4-hour fault response."),
    ("gaming", "Which plan is best for gaming?", "Fiber 300 or above with Gaming Boost; a wired connection for the console helps most."),
    ("work from home", "Which plan is best for working from home?", "Fiber 300 handles several video calls at once; pick Fiber 1000 if you upload large files."),
    ("4k streaming", "Can I stream 4K?", "Yes, Fiber 300 and above handle several 4K streams at once."),
    ("speed test", "How do I test my speed?", "Use a wired device and the speed test in the {company} app; Wi-Fi tests show lower numbers."),
    ("wifi password", "How do I change the Wi-Fi password?", "In the {company} app under Wi-Fi settings, or on the router's admin page."),
    ("parental", "Can I limit my kids' internet?", "Family Shield lets you filter content, set schedules and pause devices."),
    ("cctv", "Can I watch my CCTV remotely?", "Yes, add a Static IP and forward the camera port in the app."),
    ("students", "Is there a student discount?", "Yes, 20% off Fiber 100 and Fiber 300 with a valid student ID."),
    ("price change", "Will my price go up?", "Your price stays the same for 12 months from activation."),
    ("deposit", "Do I pay a deposit?", "No deposit on home plans; business plans need a one-month deposit."),
    ("cancel", "How do I cancel?", "Tell us in chat; service ends at the end of the billing cycle and you return the router within 15 days."),
    ("transfer", "Can I transfer my connection to someone else?", "Yes, ownership transfer at the same address takes one working day and is free."),
    ("dual band", "What's the difference between 2.4 GHz and 5 GHz?", "2.4 GHz reaches further; 5 GHz is much faster nearby. Our routers pick the best band automatically."),
]


def nice(amount, cur_per_usd):
    """Friendly local prices: 649, 1,499, 24.99, 3,900..."""
    if cur_per_usd < 3:
        return round(math.ceil(amount) - 0.01, 2)
    step = 100 if amount > 2000 else 50 if amount > 500 else 10 if amount > 100 else 1
    return int(math.ceil(amount / step) * step - (1 if step >= 10 else 0))


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9 .'-]", " ", s.lower()).split())


def load_geo():
    names = {}
    for line in (GEO / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            f = line.split("\t")
            names[f[0]] = (f[4], f[10])  # name, currency code
    cities = defaultdict(list)
    for line in (GEO / "cities15000.txt").read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if f[8] in COUNTRIES and f[7] in ("PPL", "PPLA", "PPLA2", "PPLA3", "PPLC", "PPLG"):
            # Proper-cased ASCII spellings only ("Bangalore", "Bombay"); skips romanised forms like "baeng-geollo".
            # >= 5 letters: drops airport codes and short forms that are everyday words ("man", "mad", "par").
            alts = [a for a in f[3].split(",") if a.isascii() and 5 <= len(a) <= 24 and a[0].isupper()
                    and re.fullmatch(r"[A-Za-z .'-]+", a)]
            cities[f[8]].append({"name": f[2], "lat": float(f[4]), "lon": float(f[5]), "pop": int(f[14] or 0),
                                 "tz": f[17], "alts": alts})
    return names, cities


def km(a, b):
    p = math.pi / 180
    h = (math.sin((b["lat"] - a["lat"]) * p / 2) ** 2
         + math.cos(a["lat"] * p) * math.cos(b["lat"] * p) * math.sin((b["lon"] - a["lon"]) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def build():
    names, geo = load_geo()
    out = {"source": "Fictional company. Place names: GeoNames cities15000 (CC BY 4.0, geonames.org).",
           "regions": {}, "countries": {}, "cities": [], "routers": ROUTERS, "plans": [], "addons": [], "services": [],
           "policies": [], "faqs": [], "playbooks": [], "technicians": {}}
    for code, (tenant, label, cores) in REGIONS.items():
        out["regions"][code] = {"tenant": tenant, "name": label, "countries": [c for c, v in COUNTRIES.items() if v[0] == code],
                                "backbones": [{"id": i, "label": lab, "city": city} for i, lab, city in cores]}
    first = ["Aarav", "Meera", "Lucas", "Emma", "Noah", "Sofia", "Kenji", "Yuna", "Omar", "Layla", "Mateo", "Valentina",
             "Liam", "Chloe", "Ravi", "Ananya", "Felix", "Hanna", "Diego", "Amara", "Ethan", "Mia", "Arjun", "Zara"]
    last = ["Kapoor", "Dubois", "Muller", "Rossi", "Garcia", "Silva", "Tanaka", "Kim", "Haddad", "Okafor", "Novak",
            "Lindqvist", "Patel", "Nguyen", "Santos", "Cohen", "Kowalski", "Moreau", "Hassan", "Ito"]
    tech_i = 0
    for iso, (region, n, fx, level, tax, pct, pay) in COUNTRIES.items():
        cname, currency = names[iso]
        out["countries"][iso] = {"name": cname, "region": region, "currency": currency, "fx": fx, "price_level": level,
                                 "tax": tax, "tax_pct": pct, "payments": pay}
        pool = sorted(geo[iso], key=lambda c: -c["pop"])
        chosen = []
        for c in pool:  # biggest cities, at least 40 km apart, so suburbs become areas, not separate cities
            if len(chosen) >= n:
                break
            if all(km(c, x) > 40 for x in chosen):
                chosen.append(c)
        for c in chosen:
            near = sorted((x for x in pool if x is not c and km(c, x) < 35), key=lambda x: -x["pop"])[:6]
            areas = NEIGHBOURHOODS.get(c["name"], []) + [x["name"] for x in near]
            areas = list(dict.fromkeys(areas))[:12] or [f"{c['name']} Central"]
            key = norm(c["name"])
            manual = [norm(a) for a in EXTRA_ALIASES.get(c["name"], [])]
            geo_alts = sorted({norm(a) for a in c["alts"]} - {key} - set(manual), key=len)
            aliases = list(dict.fromkeys(manual + geo_alts))[:10]
            out["cities"].append({"key": key, "name": c["name"], "country": iso, "region": region, "tz": c["tz"],
                                  "lat": round(c["lat"], 3), "lon": round(c["lon"], 3),
                                  "population": c["pop"], "aliases": aliases,
                                  "areas": [{"key": norm(a), "name": a} for a in areas]})
            techs = []
            for _ in range(2 if c["pop"] > 2_000_000 else 1):
                techs.append(f"{first[tech_i % len(first)]} {last[(tech_i * 7) % len(last)]}".lower())
                tech_i += 1
            out["technicians"][key] = techs
    for p in PLANS:
        out["plans"].append({**p, "regions": p.get("regions", list(REGIONS)),
                             "prices": {iso: nice(p["usd"] * v[3] * v[2], v[2]) for iso, v in COUNTRIES.items()
                                        if v[0] in p.get("regions", list(REGIONS))}})
    for key, name, usd, notes in ADDONS:
        out["addons"].append({"key": key, "name": name, "notes": notes,
                              "prices": {iso: nice(usd * v[3] * v[2], v[2]) for iso, v in COUNTRIES.items()}})
    for key, name, usd, eta, notes in SERVICES:
        out["services"].append({"key": key, "name": name, "turnaround": eta, "notes": notes,
                                "prices": {iso: (nice(usd * v[3] * v[2], v[2]) if usd else 0) for iso, v in COUNTRIES.items()}})
    out["policies"] = [{"key": k, "title": t, "text": x, "regions": list(REGIONS)} for k, t, x in POLICIES] + [
        {"key": k, "title": t, "text": x, "regions": [r]} for r, (k, t, x) in REGION_POLICY.items()]
    # FAQs: general ones for every region, plus per-plan, per-add-on, per-service and per-country ones.
    faqs = [{"key": k, "q": q, "a": a, "about": [], "regions": list(REGIONS)} for k, q, a in FAQ_GENERAL]
    for p in PLANS:
        rs = p.get("regions", list(REGIONS))
        faqs += [
            {"key": f"{p['key']} devices", "q": f"How many devices can {p['name']} handle?", "about": [p["key"]], "regions": rs,
             "a": f"{p['name']} comfortably handles about {p['devices']} connected devices at once."},
            {"key": f"{p['key']} speeds", "q": f"What are the speeds on {p['name']}?", "about": [p["key"]], "regions": rs,
             "a": f"{p['name']} gives {p['down']} Mbps download and {p['up']} Mbps upload."},
            {"key": f"{p['key']} good for", "q": f"Who is {p['name']} for?", "about": [p["key"]], "regions": rs,
             "a": f"{p['name']} is built for {p['good_for']}."},
            {"key": f"{p['key']} router", "q": f"Which router comes with {p['name']}?", "about": [p["key"], p["router"]], "regions": rs,
             "a": f"{p['name']} comes with the {next(r['name'] for r in ROUTERS if r['key'] == p['router'])}."},
            {"key": f"{p['key']} includes", "q": f"What's included with {p['name']}?", "about": [p["key"]], "regions": rs,
             "a": f"{p['name']} includes {', '.join(p['includes'])}."},
            {"key": f"{p['key']} lock in", "q": f"Is there a lock-in on {p['name']}?", "about": [p["key"]], "regions": rs,
             "a": f"{p['name']} has {'a ' + str(p['lock_in']) + '-month lock-in' if p['lock_in'] else 'no lock-in'}."},
        ]
    for key, name, _, notes in ADDONS:
        faqs.append({"key": f"{key} what", "q": f"What is {name}?", "a": notes, "about": [key], "regions": list(REGIONS)})
        faqs.append({"key": f"{key} add", "q": f"How do I add {name}?", "about": [key], "regions": list(REGIONS),
                     "a": f"Tell us in chat or add {name} in the app; it starts within an hour and is billed pro-rata."})
    for key, name, _, eta, notes in SERVICES:
        faqs.append({"key": f"{key} how", "q": f"How does {name.lower()} work?", "a": f"{notes} Usually takes {eta}.",
                     "about": [key], "regions": list(REGIONS)})
    for iso, c in out["countries"].items():
        faqs.append({"key": f"pay {iso}", "q": f"How can I pay in {c['name']}?", "about": [], "regions": [c["region"]],
                     "a": f"In {c['name']} you can pay by {', '.join(c['payments'])}. Prices are in {c['currency']}"
                          + (f" and include {c['tax']} ({c['tax_pct']}%)." if c["tax_pct"] else ".")})
        faqs.append({"key": f"cities {iso}", "q": f"Where do you operate in {c['name']}?", "about": [], "regions": [c["region"]],
                     "a": f"In {c['name']} we serve " + ", ".join(x["name"] for x in out["cities"] if x["country"] == iso) + "."})
    out["faqs"] = faqs
    for issue, steps in ISSUES:
        for router in [None] + [r["key"] for r in ROUTERS]:
            extra = [] if router is None else [f"On the {next(r['name'] for r in ROUTERS if r['key'] == router)}, check the status light in the app first"]
            out["playbooks"].append({"key": issue + (f" on {router}" if router else ""), "issue": issue, "router": router,
                                     "steps": extra + steps})
    return out


def places():
    """Every GeoNames town in the countries we serve, served or not: name -> [lat, lon, country]. Lets intake place a
    city we don't cover ("Goa") and find the nearest one we do with FalkorDB's distance()."""
    _, cities = load_geo()
    out = {}
    for iso, cs in cities.items():
        for c in sorted(cs, key=lambda c: -c["pop"]):  # per country, the most populous wins a shared name
            row = out.setdefault(norm(c["name"]), {})
            row.setdefault(iso, [round(c["lat"], 3), round(c["lon"], 3)])
    # states and regions people name instead of a city: their capital's coordinates
    for state, (capital, iso) in STATE_CAPITALS.items():
        hit = next((c for c in cities.get(iso, []) if capital in [norm(c["name"])] + [norm(x) for x in c["alts"]]), None)
        if hit:  # matched on the main name or a spelling variant ("Panaji" is listed as Panjim)
            out.setdefault(state, {})[iso] = [round(hit["lat"], 3), round(hit["lon"], 3)]
    return out


STATE_CAPITALS = {
    "goa": ("panaji", "IN"), "kerala": ("thiruvananthapuram", "IN"), "punjab": ("chandigarh", "IN"),
    "gujarat": ("gandhinagar", "IN"), "rajasthan": ("jaipur", "IN"), "assam": ("dispur", "IN"),
    "bihar": ("patna", "IN"), "odisha": ("bhubaneswar", "IN"), "jharkhand": ("ranchi", "IN"),
    "uttarakhand": ("dehradun", "IN"), "himachal": ("shimla", "IN"), "sikkim": ("gangtok", "IN"),
    "tamil nadu": ("chennai", "IN"), "karnataka": ("bengaluru", "IN"), "maharashtra": ("mumbai", "IN"),
    "telangana": ("hyderabad", "IN"), "west bengal": ("kolkata", "IN"), "kashmir": ("srinagar", "IN"),
    "bavaria": ("munich", "DE"), "scotland": ("edinburgh", "GB"), "wales": ("cardiff", "GB"),
    "texas": ("austin", "US"), "california": ("sacramento", "US"), "florida": ("tallahassee", "US"),
    "ontario": ("toronto", "CA"), "quebec": ("quebec", "CA"),
}


if __name__ == "__main__" and sys.argv[1:] == ["places"]:
    pl = places()
    (HERE / "places.json").write_text(json.dumps(pl, separators=(",", ":")), encoding="utf-8")
    print(f"places {len(pl)}")
    sys.exit()

if __name__ == "__main__":
    data = build()
    (HERE / "kb_world.json").write_text(json.dumps(data, indent=1, ensure_ascii=True), encoding="utf-8")
    areas = sum(len(c["areas"]) for c in data["cities"])
    steps = sum(len(p["steps"]) for p in data["playbooks"])
    print(f"regions {len(data['regions'])}, countries {len(data['countries'])}, cities {len(data['cities'])}, areas {areas}, "
          f"plans {len(data['plans'])}, addons {len(data['addons'])}, services {len(data['services'])}, "
          f"policies {len(data['policies'])}, faqs {len(data['faqs'])}, playbooks {len(data['playbooks'])} ({steps} steps), "
          f"technicians {sum(map(len, data['technicians'].values()))}")
