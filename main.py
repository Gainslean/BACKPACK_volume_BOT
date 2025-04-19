import asyncio
import base64
import random
import time
import aiohttp
import json
from colorama import Fore, Style, init
import re
from cryptography.hazmat.primitives.asymmetric import ed25519
from urllib.parse import urlencode
from datetime import datetime

init(autoreset=True)

tickers = "BTC", "SOL", "ETH"  # тикеры торговых пар

long_short = "Bid", "Ask"


window = 8000  # окно действия сигнатруры, служит корректором time_now


async def is_proxy(proxy):  # функция проверки прокси на рабоспособность

    match = re.search(r'@([^:]+)(?::|$)', proxy)
    if match:
        possible_ip = match.group(1)
        print(Fore.YELLOW + f"Проверяю {possible_ip}")


    url = "https://api.ipify.org/"
    proxy_url = f"http://{proxy}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url=url, proxy=proxy_url) as response:
            if response.status == 200:
                data = await response.text()
                if data == possible_ip:
                    print(Fore.GREEN + f"{proxy} рабочий")
                    return True
            else:
                error_text = await response.text()
                print(Fore.RED + f"Ошибка: {response.status} - {error_text}")
                return False


async def get_market_back(ticker): # функция получения цены актива на бэкпаке. возвращает текущую цену на фьючах

    start_time = time.time()

    url ="https://api.backpack.exchange/api/v1/ticker"

    params = {
        "symbol": f"{ticker}_USDC_PERP", # передаем параметр тикета
        "interval": "1d"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                print(data)
                price = data["lastPrice"]
                print(Fore.GREEN + f"Цена на BackPack = {price}")
                end_time = time.time()
                res = end_time - start_time
                print(Fore.YELLOW + f"Выполнил получение цен за {res}")
                return price
            else:
                error_text = await response.text()
                print(Fore.RED + f"Ошибка: {response.status} - {error_text}")






async def signatyre(instruction, secret, timestamp): # формирование сигнатруры для запроса. требует передачи кода запроса

    # Декодируем приватный ключ (seed)
    private_key_seed = base64.b64decode(secret)

    # Создаем объект приватного ключа из seed

    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_seed)
    # Строка для подписи
    signing_string = f"instruction={instruction}&timestamp={timestamp}&window={window}"

    # Создание подписи
    signature = private_key.sign(signing_string.encode('utf-8'))
    print()

    return signature


async def get_balance_back(api, secret, proxy): # получение баланса юсдс на бирже. возвращает текщий баланс в лендинге

    public_key_bytes = base64.b64decode(api)


    timestamp = int(time.time() * 1000)

    # Заголовки
    headers = {
        "X-API-Key": base64.b64encode(public_key_bytes).decode('utf-8'),
        "X-Signature": base64.b64encode(await signatyre(("borrowLendPositionQuery"),secret, timestamp)).decode('utf-8'),
        "X-Timestamp": str(timestamp),
        "X-Window": str(window),
        "Content-Type": "application/json"
    }

    # URL эндпоинта
    url = "https://api.backpack.exchange/api/v1/borrowLend/positions"
    #url = "https://api.backpack.exchange/api/v1/capital"


    # Отправка запроса
    async with aiohttp.ClientSession() as session:
        proxy_url = f"http://{proxy}"

        try:
            async with session.get(url, headers=headers, proxy=proxy_url) as response:
                if response.status == 200:
                    data = await response.json()
                    for item in data:
                        if item['symbol'] == 'USDC':
                            net_quantity = float(item['netQuantity'])
                            symbol = item['symbol']
                            print(Fore.GREEN + f"BALANCE BACKPACK = {net_quantity:.2f} {symbol}")
                            return f"{net_quantity:.2f}"
                else:
                    error_text = await response.text()
                    print(Fore.RED + f"Ошибка: {response.status} - {error_text}")
                    return None
        except Exception as e:
            print(Fore.RED + f"Произошла ошибка: {str(e)}")
            return None


async def order_back(size, type, cansel, secret, api, ticker, proxy): # открытие/закрытие ордера на фьючах

    # Декодируем приватный ключ (seed)
    private_key_seed = base64.b64decode(secret)

    # Создаем объект приватного ключа из seed
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_seed)

    timestamp = int(time.time() * 1000)

    if cansel == False:
        type_order = "quoteQuantity"
    else:
        type_order = "quantity"
    # Данные ордера
    order_data = {
        "orderType": "Market",
        "side": f"{type}",  # "Bid" для покупки (лонг), "Ask" для продажи (шорт)
        "symbol": f"{ticker}_USDC_PERP",
        type_order: f"{size}",
        "timeInForce": "GTC"  # Добавляем по умолчанию
    }

    # Создание подписи
    sorted_body = dict(sorted(order_data.items()))  # Сортируем параметры
    query_string = urlencode(sorted_body)  # Преобразуем в query string
    signing_string = f"instruction=orderExecute&{query_string}&timestamp={timestamp}&window={window}".encode("utf-8")

    # Подписываем
    signature = private_key.sign(signing_string)
    signature_base64 = base64.b64encode(signature).decode("utf-8")

    # Заголовки
    headers = {
        "X-API-Key": api,  # Публичный ключ в base64
        "X-Signature": signature_base64,
        "X-Timestamp": str(timestamp),
        "X-Window": str(window),
        "Content-Type": "application/json"
    }

    # URL эндпоинта
    url = "https://api.backpack.exchange/api/v1/order"


    # Отправка запроса
    async with aiohttp.ClientSession() as session:
        proxy_url = f"http://{proxy}"
        try:
            async with session.post(url, headers=headers, json=order_data, proxy=proxy_url) as response:
                if response.status == 200:
                    data = await response.json()
                    if cansel == False:
                        print(Fore.GREEN + f"Успешно открыл ордер в {ticker} на сумму {size} {type} на Бэкпак")
                    return data['id']
                else:
                    error_text = await response.text()
                    print(Fore.RED + f"Ошибка: {response.status} - {error_text}")
                    return None
        except Exception as e:
            print(Fore.RED + f"Произошла ошибка: {str(e)}")
            return None

async def get_open_position_backpack(api, secret, proxy): # ищет открытие позиции. вовзращает объем позы в токене и тип позиции

        public_key_bytes = base64.b64decode(api)


        timestamp = int(time.time() * 1000)

        # Заголовки
        headers = {
            "X-API-Key": base64.b64encode(public_key_bytes).decode('utf-8'),
            "X-Signature": base64.b64encode(await signatyre(("positionQuery"),secret, timestamp)).decode('utf-8'),
            "X-Timestamp": str(timestamp),
            "X-Window": str(window),
            "Content-Type": "application/json"
        }

        # URL эндпоинта
        url = "https://api.backpack.exchange/api/v1/position"

        # Отправка запроса
        async with aiohttp.ClientSession() as session:
            proxy_url = f"http://{proxy}"
            try:
                async with session.get(url, headers=headers, proxy=proxy_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        position_id = data[0]['positionId']
                        print(Fore.GREEN + f"Найдена позиция  {position_id}")
                        return (float(data[0]['netQuantity'])), "Ask" if float(data[0]['netQuantity']) > 0 else "Bid"
                    else:
                        error_text = await response.text()
                        print(Fore.RED + f"Ошибка: {response.status} - {error_text}")
                        return None
            except Exception as e:
                print(Fore.RED + f"Произошла ошибка: {str(e)}")
                return None

async def order_cansel_backpack(api, secret, ticker, proxy): # закртытие позиции на бирже

    order_info = await get_open_position_backpack(api=api, secret=secret, proxy=proxy)
    print(Fore.GREEN + f"Получил данные о позиции на бэкпак, size {order_info[0]}  = {ticker} type = {order_info[1]}")
    print()

    print(Fore.GREEN + "Закрываю позу на бэке")
    print()
    info_back = await order_back(size=abs(order_info[0]), type=order_info[1], cansel=True, api=api, secret=secret, proxy=proxy, ticker=ticker)

    if info_back:
        print(Fore.GREEN + f"Успешно закрыл позицию")
    else:
        i = 0
        while i < 3:
            i += 1
            print(Fore.RED + f"При закрытии позы на бэке ошибка, пробую снова."
                    f"Попытка номер {i}")
            info_back = await order_back(size=abs(order_info[0]), type=order_info[1], cansel=True, api=api, secret=secret, proxy=proxy, ticker=ticker)
            if info_back:
                print(Fore.GREEN + f"Успешно закрыл позицию")
                break
            else:
                print(Fore.RED + "Снова ощибка")
                await asyncio.sleep(0.1)
                if i ==3:
                    print(Fore.RED + "Сделал 3 попытки закрытия позиции, что-то пошло не так, проверь руками")
                    exit()

async def start_main():

    while True:

        with open("key.json", "r", encoding="utf-8") as file:
            data = json.load(file)
        try:
            for i in range(7):
                i+=1
                formatted_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(formatted_datetime)

                api1 = data[f"key_pair{i}"][f"api1"]
                secret1 = data[f"key_pair{i}"][f"secret1"]

                api2 = data[f"key_pair{i}"][f"api2"]
                secret2 = data[f"key_pair{i}"][f"secret2"]

                proxy = data[f"key_pair{i}"]["proxy"]

                connect = await is_proxy(data[f"key_pair{i}"]["proxy"])


                if connect == True:

                    z = i
                    await main(api1, secret1, api2, secret2, proxy, z)

                    time_sleep_after = random.randint(20 * 60, 30 * 60)  # задержка перед следующим циклом

                    print()
                    print(f"Выполнил действия для счета {i}, ожидаю  {time_sleep_after/60} минут перед следующим")
                    formatted_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(formatted_datetime)
                    await asyncio.sleep(time_sleep_after)
                    print()
                else:
                    print(f"Прокси на аке {i} не рабочий")

        except Exception as e:
            print(Fore.RED + f"Произошла ошибка: {str(e)}")




async def main(api1, secret1, api2, secret2, proxy, z):

    total = []

    coms = []

    rang = random.randint(5, 10)

    for i in range(rang):

        ticker = random.choice(tickers)

        i += 1

        positions = random.choice(long_short)

        time_sleep = random.randint(100, 500) # время задержки между открытием и закрытием поз

        time_sleep_after = random.randint(3*60, 15*60) # задержка перед следующим циклом

        om = await get_balance_back(api=api1, secret=secret1, proxy=proxy)

        size = int(float(om) * 0.95) # размер позиции, получаем от мейн счета и уменьшаем на 5% для соблюдения погрешности

        #size = 1500

        print(Fore.MAGENTA + f"Отрабатываю цикл {i}")
        print()
        formatted_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(formatted_datetime)


        positions2 = positions

        print(Fore.MAGENTA + f"Выбрал {positions}")
        print()


        balance_back = await get_balance_back(api=api1, secret=secret1, proxy=proxy)
        if balance_back:
            print(Fore.GREEN + "Баланс BACKPACK main успешно получен:")
            print(Fore.YELLOW + balance_back)
        else:
            print(Fore.RED + "Не удалось получить баланс")
            break

        balance_back_sub = await get_balance_back(api=api2, secret=secret2, proxy=proxy)
        if balance_back_sub:
            print(Fore.GREEN + "Баланс BACKPACK Sub успешно получен:")
            print(Fore.YELLOW + balance_back_sub)
        else:
            print(Fore.RED + "Не удалось получить баланс")
            break


        # Одновременное открытие позиций
        if positions == "Ask":
            tasks = [
                order_back(size=size, type="Ask", cansel=False, api=api1, secret=secret1, ticker=ticker, proxy=proxy),
                order_back(size=size, type="Bid", cansel=False, api=api2, secret=secret2, ticker=ticker, proxy=proxy)
            ]
        else:  # positions == "Bid"
            tasks = [
                order_back(size=size, type="Bid", cansel=False, api=api1, secret=secret1, ticker=ticker, proxy=proxy),
                order_back(size=size, type="Ask", cansel=False, api=api2, secret=secret2, ticker=ticker, proxy=proxy)
            ]
        print()
        print("Открываю позиции на обоих аккаунтах одновременно")
        await asyncio.gather(*tasks)  # Параллельное выполнение
        print(Fore.MAGENTA + "Позы открыты на обоих аккаунтах")
        total.append(size*2)
        print()
        print(f"Ожидаю {time_sleep} секунд перед закрытием позиций")
        await asyncio.sleep(time_sleep)

        # Одновременное закрытие позиций
        print(Fore.GREEN + "Закрываю позиции на обоих аккаунтах одновременно")
        await asyncio.gather(
            order_cansel_backpack(api=api1, secret=secret1, ticker=ticker, proxy=proxy),
            order_cansel_backpack(api=api2, secret=secret2, ticker=ticker, proxy=proxy)
        )
        print(Fore.MAGENTA + "Позы закрыты на обоих аккаунтах")
        print()
        total.append(size * 2)
        print("Отработал цикл")
        print()
        balance_back2 = await get_balance_back(api=api1, secret=secret1, proxy=proxy)
        if balance_back2:
            print(Fore.MAGENTA + "Баланс BACKPACK main после сделки успешно получен:")
            print(Fore.YELLOW + balance_back2)
        else:
            print(Fore.RED + "Не удалось получить баланс")
            break

        balance_back_sub2 = await get_balance_back(api=api2, secret=secret2, proxy=proxy)
        if balance_back_sub2:
            print(Fore.MAGENTA + "Баланс BACKPACK Sub после сделки успешно получен:")
            print(Fore.YELLOW + balance_back_sub2)
        else:
            print(Fore.RED + "Не удалось получить баланс")
            break

        errow1 = float(balance_back2) - float(balance_back)
        errow2 = float(balance_back_sub2) - float(balance_back_sub)
        abc = abs(errow1-errow2)
        coms.append(errow1+errow2)

        print(Fore.MAGENTA + f"Разница на мейн {errow1}")
        print()
        print(Fore.MAGENTA + f"Разница на суб {errow2}")
        print()
        print(Fore.YELLOW + f"Разница составила {errow1+errow2}")
        print()
        if i == rang:
            print("Отработал все циклы для счета")
            break
        print(f"Ожидаю перед новой сделкой {time_sleep_after / 60}")
        formatted_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(formatted_datetime)
        await asyncio.sleep(time_sleep_after)
    print()
    print(Fore.YELLOW + f"За цикл набил {sum(total)}")
    print()
    print(Fore.YELLOW + f"Потрачено было {sum(coms)}")

    # запрись данных объема и затрат на ак
    with open("key.json", "r", encoding="utf-8") as file:
        data = json.load(file)


    data[f"key_pair{z}"]["volume"] += sum(total)
    data[f"key_pair{z}"]["coms"] += sum(coms)




    with open("key.json", "w", encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)
    print()
    print("Сделал запись данных")
    formatted_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(formatted_datetime)



if __name__ == "__main__":
    asyncio.run(start_main())
