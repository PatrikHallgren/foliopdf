"""Scan one Letter page from the local HP M276nw document feeder."""

from __future__ import annotations

import os
import socket
import struct
import subprocess
from urllib.request import ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET


SCANNER_NAME = "NPIB85342.local"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
SOAP_START = (
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:SOAP-ENC="http://www.w3.org/2003/05/soap-encoding" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
    'xmlns:wscn="http://tempuri.org/wscn.xsd"><SOAP-ENV:Body>'
)
SOAP_END = '</SOAP-ENV:Body></SOAP-ENV:Envelope>'


class ScanError(RuntimeError):
    """A scanner connection, protocol, or feeder error."""


def _scanner_url() -> str:
    override = os.environ.get("FOLIO_SCANNER_URL")
    if override:
        return override.rstrip("/") + "/"
    try:
        result = subprocess.run(
            ["avahi-resolve-host-name", "-4", SCANNER_NAME],
            check=True, capture_output=True, text=True, timeout=6,
        )
        address = result.stdout.split()[-1]
        socket.inet_aton(address)
    except (FileNotFoundError, IndexError, OSError, subprocess.SubprocessError) as exc:
        raise ScanError("HP scanner not found. Check that it is on and on the same network.") from exc
    return f"http://{address}:8289/"


def _post(opener, url: str, body: str, *, timeout: int) -> bytes:
    request = Request(
        url, body.encode("utf-8"),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except OSError as exc:
        raise ScanError(f"Could not communicate with the HP scanner: {exc}") from exc
    if len(data) > MAX_RESPONSE_BYTES:
        raise ScanError("The scanner sent an unexpectedly large image.")
    return data


def _soap_value(data: bytes, name: str) -> str:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ScanError("The scanner sent an unreadable response.") from exc
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "Fault":
            raise ScanError("The HP scanner rejected the scan request.")
        if element.tag.rsplit("}", 1)[-1] == name:
            return (element.text or "").strip()
    raise ScanError(f"The scanner did not report {name}.")


def _dime_image(data: bytes) -> bytes:
    """Join the DIME attachment chunks without their per-chunk headers."""
    offset = 0
    records = 0
    image_chunks: list[bytes] = []
    while offset < len(data):
        if offset + 12 > len(data):
            raise ScanError("The scanner image ended unexpectedly.")
        flags, _type = data[offset], data[offset + 1]
        options_length, id_length, type_length, body_length = struct.unpack_from(">HHHI", data, offset + 2)
        if flags >> 3 != 1:
            raise ScanError("The scanner used an unsupported image format.")
        cursor = offset + 12
        for length in (options_length, id_length, type_length):
            cursor += (length + 3) & ~3
        next_record = cursor + ((body_length + 3) & ~3)
        if next_record > len(data):
            raise ScanError("The scanner image ended unexpectedly.")
        if records:
            image_chunks.append(data[cursor:cursor + body_length])
        offset = next_record
        records += 1
    image = b"".join(image_chunks)
    if records < 2 or not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
        raise ScanError("The scanner did not return a complete JPEG page.")
    return image


def scan_feeder_page() -> bytes:
    """Return a 300 dpi color JPEG of one Letter page from the feeder."""
    url = _scanner_url()
    opener = build_opener(ProxyHandler({}))
    status = _post(opener, url, SOAP_START + "<wscn:GetScannerElements/>" + SOAP_END, timeout=15)
    if _soap_value(status, "PaperInADF").lower() != "true":
        raise ScanError("The document feeder is empty. Load a page and try again.")

    settings = (
        "<wscn:CreateScanJobRequest><ScanIdentifier/><ScanTicket><JobDescription/>"
        "<DocumentParameters><Format>jfif</Format><CompressionQualityFactor>0</CompressionQualityFactor>"
        "<ImagesToTransfer>1</ImagesToTransfer><InputSource>ADF</InputSource>"
        "<ContentType>Auto</ContentType><InputSize><InputMediaSize><Width>8500</Width>"
        "<Height>11000</Height></InputMediaSize><DocumentSizeAutoDetect>false"
        "</DocumentSizeAutoDetect></InputSize><Exposure><AutoExposure>false</AutoExposure>"
        "<ExposureSettings><Contrast>0</Contrast><Brightness>0</Brightness>"
        "</ExposureSettings></Exposure><MediaSides><MediaFront><ScanRegion>"
        "<ScanRegionXOffset>0</ScanRegionXOffset><ScanRegionYOffset>0</ScanRegionYOffset>"
        "<ScanRegionWidth>8500</ScanRegionWidth><ScanRegionHeight>11000</ScanRegionHeight>"
        "</ScanRegion><ColorProcessing>RGB24</ColorProcessing><Resolution><Width>300</Width>"
        "<Height>300</Height></Resolution></MediaFront></MediaSides></DocumentParameters>"
        "<RetrieveImageTimeout>300</RetrieveImageTimeout><ScanManufacturingParameters>"
        "<DisableImageProcessing>false</DisableImageProcessing></ScanManufacturingParameters>"
        "</ScanTicket></wscn:CreateScanJobRequest>"
    )
    job_response = _post(opener, url, SOAP_START + settings + SOAP_END, timeout=30)
    job_id = _soap_value(job_response, "JobId")
    if not job_id.isdecimal():
        raise ScanError("The scanner returned an invalid job number.")
    retrieve = (
        f"<wscn:RetrieveImageRequest><JobId>{job_id}</JobId><JobToken/>"
        "<DocumentDescription/></wscn:RetrieveImageRequest>"
    )
    image_response = _post(opener, url, SOAP_START + retrieve + SOAP_END, timeout=120)
    return _dime_image(image_response)
