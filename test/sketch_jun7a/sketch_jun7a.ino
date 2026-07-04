#include <WiFi.h>
#include <HTTPClient.h>

const char* WIFI_SSID =
"Familia sepulveda_2.4G";

const char* WIFI_PASSWORD =
"9611170412";

const char* SERVER_URL =
"http://192.168.2.12:8000/telemetry";

float temperature = 4.0;
float humidity = 65.0;

unsigned long lastSend = 0;
const unsigned long interval = 10000;

void connectWiFi()
{
    WiFi.begin(
        WIFI_SSID,
        WIFI_PASSWORD
    );

    Serial.print("Conectando");

    while (
        WiFi.status()
        != WL_CONNECTED
    )
    {
        delay(500);
        Serial.print(".");
    }

    Serial.println();
    Serial.println("WiFi conectado");
    Serial.print("IP ESP32: ");
    Serial.println(
        WiFi.localIP()
    );
}

void sendTelemetry()
{
    if (
        WiFi.status()
        != WL_CONNECTED
    )
    {
        return;
    }

    temperature += random(-5, 6) * 0.1;
    humidity += random(-3, 4) * 0.1;

    temperature =
        constrain(
            temperature,
            2.0,
            8.0
        );

    humidity =
        constrain(
            humidity,
            40.0,
            90.0
        );

    String json =
        "{"
        "\"device_id\":\"esp32-coldchain-001\","
        "\"temperature\":" + String(temperature,1) + ","
        "\"humidity\":" + String(humidity,1) + ","
        "\"battery\":95,"
        "\"status\":\"OK\""
        "}";

    Serial.println();
    Serial.println("Enviando:");
    Serial.println(json);

    HTTPClient http;

    http.begin(
        SERVER_URL
    );

    http.addHeader(
        "Content-Type",
        "application/json"
    );

    int code =
        http.POST(json);

    Serial.print(
        "HTTP CODE: "
    );

    Serial.println(
        code
    );

    if (code > 0)
    {
        String response =
            http.getString();

        Serial.println();
        Serial.println(
            "RESPUESTA:"
        );

        Serial.println(
            response
        );
    }

    http.end();
}

void setup()
{
    Serial.begin(115200);

    delay(1000);

    connectWiFi();

    randomSeed(
        millis()
    );
}

void loop()
{
    if (
        millis() - lastSend
        >= interval
    )
    {
        lastSend =
            millis();

        sendTelemetry();
    }
}