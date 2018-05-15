package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"math/rand"
	"os"
	"strconv"
	"time"

	"github.com/Shopify/sarama"
	"github.com/alecthomas/units"
	metrics "github.com/rcrowley/go-metrics"
)

const (
	letterBytes   = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
	letterIdxBits = 6                    // 6 bits to represent a letter index
	letterIdxMask = 1<<letterIdxBits - 1 // All 1-bits, as many as letterIdxBits
	letterIdxMax  = 63 / letterIdxBits   // # of letter indices fitting in 63 bits
)

var (
	topic   = flag.String("topic", "", "Kafka Topic")
	broker  = flag.String("broker", "", "Kafka Broker")
	verbose = flag.Bool("verbose", false, "Print Verbose Messaging")
	msgChan = make(chan *string, 1000)
	src     = rand.NewSource(time.Now().UnixNano())
	signals = make(chan os.Signal, 1)
)

func init() {
	rand.Seed(time.Now().UTC().UnixNano())
}

func randString(n int) string {
	b := make([]byte, n)
	for i, cache, remain := n-1, src.Int63(), letterIdxMax; i >= 0; {
		if remain == 0 {
			cache, remain = src.Int63(), letterIdxMax
		}
		if idx := int(cache & letterIdxMask); idx < len(letterBytes) {
			b[i] = letterBytes[idx]
			i--
		}
		cache >>= letterIdxBits
		remain--
	}

	return string(b)
}

func sendMsgs(producer sarama.AsyncProducer) error {
	consumers := []string{"consumera", "consumerb"}
	producers := []string{"producera", "producerb"}
	for {
		dest := consumers[rand.Intn(2)]
		prod := producers[rand.Intn(2)]
		r := rand.Intn(2001-100) + 100
		for i := 0; i < r; i++ {
			msg := randString(10000)
			data, err := json.Marshal(map[string]string{"log": msg, "dest": dest, "prod": prod, "num": strconv.Itoa(i)})
			if err != nil {
				fmt.Println(err)
				return err
			}
			m := &sarama.ProducerMessage{
				Topic: *topic,
				Key:   sarama.ByteEncoder("log"),
				Value: sarama.ByteEncoder(data),
			}

			select {
			case producer.Input() <- m:
			case <-signals:
				break
			case err = <-producer.Errors():
				if *verbose {
					fmt.Println(err)
				}
			case <-producer.Successes():
			}
		}
		time.Sleep(time.Millisecond)
	}
	return nil
}

func main() {
	flag.Parse()
	if *topic == "" {
		fmt.Println("Topic Required")
		os.Exit(1)
	}
	if *broker == "" {
		fmt.Println("Broker Required")
		os.Exit(1)
	}
	appMetricRegistry := metrics.NewRegistry()
	conf := sarama.NewConfig()
	conf.Producer.RequiredAcks = sarama.WaitForAll
	conf.Producer.Return.Successes = true
	conf.Producer.Return.Errors = true
	conf.Producer.MaxMessageBytes = 54857600
	conf.MetricRegistry = metrics.NewPrefixedChildRegistry(appMetricRegistry, "sarama.")
	conf.Producer.RequiredAcks = sarama.WaitForLocal
	meter := metrics.GetOrRegisterMeter("outgoing-byte-rate", conf.MetricRegistry)
	producer, err := sarama.NewAsyncProducer([]string{*broker}, conf)
	defer producer.Close()
	if err != nil {
		fmt.Printf("Failed to start Sarama producer: %s\n", err)
		os.Exit(1)
	}

	go func() {
		for {
			b := meter.Rate1() / float64(units.MB)
			fmt.Printf("%f MB/s\r", b)
			time.Sleep(time.Second)
		}
	}()

	go sendMsgs(producer)

	select {}

	os.Exit(0)
}
