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
	msgChan = make(chan *string, 1000)
	src     = rand.NewSource(time.Now().UnixNano())
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

func sendMsgs(c chan<- *sarama.ProducerMessage) error {
	consumers := []string{"consumera", "consumerb"}
	producers := []string{"producera", "producerb"}
	dest := consumers[rand.Intn(2)]
	prod := producers[rand.Intn(2)]
	r := rand.Intn(2001-100) + 100
	for {
		for i := 0; i < r; i++ {
			msg := randString(50)
			data, err := json.Marshal(map[string]string{"log": msg, "dest": dest, "prod": prod, "num": strconv.Itoa(i)})
			if err != nil {
				fmt.Println(err)
				return err
			}
			c <- &sarama.ProducerMessage{
				Topic: *topic,
				Key:   sarama.ByteEncoder("log"),
				Value: sarama.ByteEncoder(data),
			}
		}
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
	meter := metrics.GetOrRegisterMeter("outgoing-byte-rate", conf.MetricRegistry)
	conf.Producer.RequiredAcks = sarama.WaitForLocal
	producer, err := sarama.NewAsyncProducer([]string{*broker}, conf)
	if err != nil {
		fmt.Printf("Failed to start Sarama producer: %s\n", err)
		os.Exit(1)
	}

	go func() {
		for {
			fmt.Printf("%d\r", int(meter.Rate1()))
			time.Sleep(time.Second)
		}
	}()

	go sendMsgs(producer.Input())

	for {
		select {
		case err = <-producer.Errors():
			fmt.Println(err)
		case <-producer.Successes():
		}
	}

	os.Exit(0)
}
