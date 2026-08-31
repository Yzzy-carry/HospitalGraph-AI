
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

CREATE DATABASE /*!32312 IF NOT EXISTS*/ `hospital_graph` /*!40100 DEFAULT CHARACTER SET utf8mb3 */ /*!80016 DEFAULT ENCRYPTION='N' */;

USE `hospital_graph`;
DROP TABLE IF EXISTS `disease_drugs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `disease_drugs` (
  `disease_id` int NOT NULL,
  `drug_id` int NOT NULL,
  PRIMARY KEY (`disease_id`,`drug_id`),
  KEY `drug_id` (`drug_id`),
  CONSTRAINT `disease_drugs_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`),
  CONSTRAINT `disease_drugs_ibfk_2` FOREIGN KEY (`drug_id`) REFERENCES `drugs` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `disease_drugs` WRITE;
/*!40000 ALTER TABLE `disease_drugs` DISABLE KEYS */;
INSERT INTO `disease_drugs` VALUES (1,1),(4,1),(15,1),(1,2),(1,3),(1,4),(15,4),(2,5),(10,5),(11,5),(12,5),(2,6),(2,7),(16,7),(17,7),(3,8),(3,9),(3,10),(4,11),(4,13),(5,14),(5,15),(5,16),(6,17),(13,17),(16,17),(17,17),(20,17),(22,17),(24,17),(6,18),(6,19),(7,20),(7,21),(7,22),(8,23),(8,24),(8,25),(9,26),(9,27),(9,28),(10,29),(11,29),(11,30),(13,30),(12,31),(14,31),(13,32),(14,33),(14,34),(15,35),(15,36),(16,37),(17,38),(18,39),(18,40),(18,41),(18,42),(19,43),(19,44),(20,45),(20,46),(21,47),(21,48),(21,49),(22,50),(23,51),(23,52),(24,53),(24,54);
/*!40000 ALTER TABLE `disease_drugs` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `disease_symptoms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `disease_symptoms` (
  `disease_id` int NOT NULL,
  `symptom_id` int NOT NULL,
  PRIMARY KEY (`disease_id`,`symptom_id`),
  KEY `symptom_id` (`symptom_id`),
  CONSTRAINT `disease_symptoms_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`),
  CONSTRAINT `disease_symptoms_ibfk_2` FOREIGN KEY (`symptom_id`) REFERENCES `symptoms` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `disease_symptoms` WRITE;
/*!40000 ALTER TABLE `disease_symptoms` DISABLE KEYS */;
INSERT INTO `disease_symptoms` VALUES (1,1),(15,1),(1,2),(2,2),(15,2),(1,3),(15,3),(1,4),(10,4),(11,4),(13,4),(14,4),(24,4),(2,5),(10,5),(11,5),(12,5),(14,5),(16,5),(17,5),(18,5),(20,5),(22,5),(2,6),(9,6),(16,6),(17,6),(18,6),(2,7),(16,7),(18,7),(3,9),(3,10),(3,11),(18,11),(3,12),(7,12),(17,12),(19,12),(4,13),(4,14),(4,15),(5,15),(17,15),(24,15),(4,16),(5,18),(19,18),(5,19),(15,19),(19,19),(5,20),(24,20),(6,21),(6,22),(6,23),(6,24),(7,25),(21,25),(7,26),(7,27),(10,27),(8,29),(14,29),(8,30),(8,31),(8,32),(9,33),(9,34),(15,34),(16,34),(9,36),(10,37),(10,38),(11,38),(13,38),(14,38),(24,38),(11,39),(11,40),(12,41),(12,42),(12,43),(12,44),(13,44),(13,45),(14,46),(17,47),(17,48),(18,49),(18,50),(19,51),(20,52),(20,53),(20,54),(21,55),(21,56),(21,57),(22,58),(22,59),(22,60),(23,61),(23,62),(23,63),(23,64),(24,65);
/*!40000 ALTER TABLE `disease_symptoms` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `disease_tests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `disease_tests` (
  `disease_id` int NOT NULL,
  `test_id` int NOT NULL,
  PRIMARY KEY (`disease_id`,`test_id`),
  KEY `test_id` (`test_id`),
  CONSTRAINT `disease_tests_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`),
  CONSTRAINT `disease_tests_ibfk_2` FOREIGN KEY (`test_id`) REFERENCES `tests` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `disease_tests` WRITE;
/*!40000 ALTER TABLE `disease_tests` DISABLE KEYS */;
INSERT INTO `disease_tests` VALUES (1,1),(5,1),(15,1),(1,2),(15,2),(1,3),(15,3),(2,4),(16,4),(18,4),(2,5),(10,5),(11,5),(12,5),(14,5),(16,5),(17,5),(19,5),(21,5),(22,5),(2,6),(3,7),(3,8),(3,9),(4,10),(24,10),(4,11),(6,11),(24,11),(4,12),(5,13),(5,15),(7,15),(6,16),(20,16),(6,17),(7,20),(12,20),(13,20),(7,21),(8,22),(8,23),(8,24),(19,24),(9,25),(9,26),(21,26),(9,27),(10,28),(11,28),(13,28),(10,29),(13,29),(11,30),(12,31),(14,32),(17,33),(18,34),(18,35),(19,36),(20,37),(22,38),(23,39),(23,40);
/*!40000 ALTER TABLE `disease_tests` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `diseases`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `diseases` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL,
  `icon` varchar(5) DEFAULT NULL,
  `dept` varchar(20) DEFAULT NULL,
  `severity` varchar(10) DEFAULT NULL,
  `cause` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `diseases` WRITE;
/*!40000 ALTER TABLE `diseases` DISABLE KEYS */;
INSERT INTO `diseases` VALUES (1,'急性心梗','','心内科','危急','冠状动脉粥样硬化斑块破裂→血栓→冠脉急性闭塞。高危因素：高血脂、高血压、吸烟、糖尿病、肥胖、家族史。'),(2,'肺炎','','呼吸科','严重','细菌/病毒/真菌感染肺部。易感：免疫力低下、长期卧床、吸烟、慢阻肺。'),(3,'2型糖尿病','','内分泌科','中度','胰岛素抵抗+分泌不足。病因：遗传+肥胖+久坐+高热量饮食。'),(4,'脑卒中','','神经内科','危急','脑血管破裂或堵塞→脑组织损伤。缺血性80%+出血性20%。核心危险因素：高血压、房颤。'),(5,'高血压','','心内科','轻度','原发性占95%。病因：遗传+高盐+肥胖+精神应激+缺乏运动+过量饮酒。'),(6,'骨折','','骨科','中度','外伤/骨质疏松→骨连续性断裂。'),(7,'慢性肾病','','肾内科','严重','糖尿病肾病+高血压肾损害+慢性肾炎→肾功能进行性下降。'),(8,'消化性溃疡','','消化内科','轻度','Hp感染70%+NSAIDs长期使用。胃酸和胃蛋白酶自身消化。'),(9,'哮喘','','呼吸科','中度','气道慢性炎症+高反应性+可逆性气流受限。遗传过敏体质+环境过敏原。'),(10,'急性阑尾炎','','普外科','严重','阑尾管腔阻塞（粪石、淋巴增生）+细菌感染→急性化脓性炎症，可进展为穿孔。'),(11,'急性胆囊炎','','普外科','严重','胆囊结石嵌顿+细菌感染→胆囊壁急性炎症。约80%病例合并胆结石。'),(12,'尿路感染','','泌尿外科','中度','细菌（大肠杆菌为主）经尿道上行感染膀胱或肾脏。女性尿道短，更易患病。'),(13,'肾结石','','泌尿外科','中度','草酸钙等晶体在尿液浓缩时析出、聚集成石。饮水不足、高草酸饮食是主要诱因。'),(14,'急性胃肠炎','','消化内科','中度','进食不洁或生冷食物→细菌、病毒感染胃肠道黏膜。夏秋季高发。'),(15,'心绞痛','','心内科','严重','冠脉粥样硬化→管腔狭窄→心肌暂时性缺血。劳累、情绪激动诱发，休息或含服硝酸甘油可缓解。'),(16,'急性支气管炎','','呼吸科','轻度','病毒或细菌感染支气管黏膜。多继发于感冒，吸烟者症状更重。'),(17,'流行性感冒','','呼吸科','中度','甲/乙型流感病毒经飞沫传播→急性呼吸道感染。冬春季高发，传染性强。'),(18,'肺结核','','感染科','严重','结核分枝杆菌经呼吸道传播→肺部慢性感染。免疫力低下者更易发病。'),(19,'缺铁性贫血','','血液科','中度','铁摄入不足、吸收障碍或慢性失血→血红蛋白合成减少。'),(20,'痛风','','风湿免疫科','中度','嘌呤代谢紊乱→血尿酸升高→尿酸盐结晶沉积关节。高嘌呤饮食、饮酒诱发。'),(21,'荨麻疹','','皮肤科','轻度','食物、药物、感染或物理刺激→肥大细胞释放组胺→风团伴瘙痒。'),(22,'中耳炎','','耳鼻喉科','轻度','咽鼓管功能障碍+细菌/病毒感染→中耳炎症。儿童咽鼓管短平，更易患。'),(23,'急性结膜炎','','眼科','轻度','细菌/病毒感染或过敏刺激→结膜急性炎症。传染性强，夏秋季高发。'),(24,'偏头痛','','神经内科','中度','神经血管调节异常→反复发作性头痛。睡眠不足、情绪波动、饮酒为常见诱因。');
/*!40000 ALTER TABLE `diseases` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `drugs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `drugs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(30) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=55 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `drugs` WRITE;
/*!40000 ALTER TABLE `drugs` DISABLE KEYS */;
INSERT INTO `drugs` VALUES (42,'乙胺丁醇'),(8,'二甲双胍'),(53,'佐米曲普坦'),(13,'依达拉奉'),(22,'促红素'),(24,'克拉霉素'),(40,'利福平'),(20,'厄贝沙坦'),(34,'口服补液盐'),(37,'右美沙芬'),(41,'吡嗪酰胺'),(32,'坦索罗辛'),(18,'头孢唑林'),(5,'头孢曲松'),(38,'奥司他韦'),(23,'奥美拉唑'),(28,'孟鲁司特'),(30,'山莨菪碱'),(31,'左氧氟沙星'),(51,'左氧氟沙星滴眼液'),(27,'布地奈德'),(17,'布洛芬'),(39,'异烟肼'),(9,'格列美脲'),(54,'氟桂利嗪'),(14,'氨氯地平'),(7,'氨溴索'),(2,'氯吡格雷'),(47,'氯雷他定'),(26,'沙丁胺醇'),(49,'炉甘石洗剂'),(29,'甲硝唑'),(16,'硝苯地平'),(4,'硝酸甘油'),(43,'硫酸亚铁'),(21,'碳酸氢钠'),(45,'秋水仙碱'),(52,'红霉素眼膏'),(44,'维生素C'),(15,'缬沙坦'),(35,'美托洛尔'),(3,'肝素'),(10,'胰岛素'),(33,'蒙脱石散'),(48,'西替利嗪'),(19,'钙剂'),(25,'铋剂'),(1,'阿司匹林'),(6,'阿奇霉素'),(36,'阿托伐他汀'),(11,'阿替普酶'),(50,'阿莫西林'),(46,'非布司他');
/*!40000 ALTER TABLE `drugs` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `hospitals`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hospitals` (
  `id` char(1) NOT NULL,
  `name` varchar(50) NOT NULL,
  `color` varchar(10) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `hospitals` WRITE;
/*!40000 ALTER TABLE `hospitals` DISABLE KEYS */;
INSERT INTO `hospitals` VALUES ('A','中心医院','#2563eb'),('B','市第一人民医院','#0891b2'),('C','附属第三医院','#7c3aed'),('D','省第二人民医院','#059669'),('E','妇幼保健院','#d97706'),('F','开发区医院','#dc2626');
/*!40000 ALTER TABLE `hospitals` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `prevalence_rates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `prevalence_rates` (
  `disease_id` int NOT NULL,
  `hospital_id` char(1) NOT NULL,
  `rate` decimal(5,4) DEFAULT NULL,
  PRIMARY KEY (`disease_id`,`hospital_id`),
  KEY `hospital_id` (`hospital_id`),
  CONSTRAINT `prevalence_rates_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`),
  CONSTRAINT `prevalence_rates_ibfk_2` FOREIGN KEY (`hospital_id`) REFERENCES `hospitals` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `prevalence_rates` WRITE;
/*!40000 ALTER TABLE `prevalence_rates` DISABLE KEYS */;
INSERT INTO `prevalence_rates` VALUES (1,'A',0.0800),(1,'B',0.0600),(1,'C',0.0400),(1,'D',0.0700),(1,'E',0.0300),(1,'F',0.0500),(2,'A',0.1800),(2,'B',0.2000),(2,'C',0.2200),(2,'D',0.1900),(2,'E',0.1500),(2,'F',0.1700),(3,'A',0.1500),(3,'B',0.1400),(3,'C',0.1200),(3,'D',0.1300),(3,'E',0.0800),(3,'F',0.1000),(4,'A',0.0700),(4,'B',0.0600),(4,'C',0.0500),(4,'D',0.0600),(4,'E',0.0200),(4,'F',0.0300),(5,'A',0.2200),(5,'B',0.2400),(5,'C',0.2000),(5,'D',0.2300),(5,'E',0.1800),(5,'F',0.2100),(6,'A',0.1000),(6,'B',0.1200),(6,'C',0.1400),(6,'D',0.1100),(6,'E',0.0600),(6,'F',0.1300),(7,'A',0.0500),(7,'B',0.0400),(7,'C',0.0600),(7,'D',0.0500),(7,'E',0.0300),(7,'F',0.0400),(8,'A',0.0800),(8,'B',0.0700),(8,'C',0.0900),(8,'D',0.0800),(8,'E',0.0500),(8,'F',0.0700),(9,'A',0.0700),(9,'B',0.0700),(9,'C',0.0800),(9,'D',0.0800),(9,'E',0.0400),(9,'F',0.0600),(10,'A',0.0500),(10,'B',0.0600),(10,'C',0.0400),(10,'D',0.0600),(10,'E',0.0300),(10,'F',0.0400),(11,'A',0.0500),(11,'B',0.0400),(11,'C',0.0400),(11,'D',0.0600),(11,'E',0.0200),(11,'F',0.0300),(12,'A',0.0500),(12,'B',0.0600),(12,'C',0.0500),(12,'D',0.0400),(12,'E',0.0700),(12,'F',0.0600),(13,'A',0.0400),(13,'B',0.0500),(13,'C',0.0400),(13,'D',0.0500),(13,'E',0.0200),(13,'F',0.0400),(14,'A',0.0600),(14,'B',0.0700),(14,'C',0.0600),(14,'D',0.0600),(14,'E',0.0800),(14,'F',0.0700),(15,'A',0.0600),(15,'B',0.0500),(15,'C',0.0400),(15,'D',0.0600),(15,'E',0.0200),(15,'F',0.0400),(16,'A',0.0700),(16,'B',0.0600),(16,'C',0.0600),(16,'D',0.0500),(16,'E',0.0700),(16,'F',0.0600),(17,'A',0.0600),(17,'B',0.0700),(17,'C',0.0600),(17,'D',0.0500),(17,'E',0.0800),(17,'F',0.0600),(18,'A',0.0400),(18,'B',0.0300),(18,'C',0.0400),(18,'D',0.0500),(18,'E',0.0100),(18,'F',0.0300),(19,'A',0.0500),(19,'B',0.0500),(19,'C',0.0400),(19,'D',0.0400),(19,'E',0.0700),(19,'F',0.0500),(20,'A',0.0500),(20,'B',0.0400),(20,'C',0.0400),(20,'D',0.0500),(20,'E',0.0100),(20,'F',0.0300),(21,'A',0.0400),(21,'B',0.0500),(21,'C',0.0400),(21,'D',0.0400),(21,'E',0.0600),(21,'F',0.0500),(22,'A',0.0300),(22,'B',0.0400),(22,'C',0.0300),(22,'D',0.0300),(22,'E',0.0800),(22,'F',0.0500),(23,'A',0.0500),(23,'B',0.0600),(23,'C',0.0500),(23,'D',0.0400),(23,'E',0.0600),(23,'F',0.0700),(24,'A',0.0400),(24,'B',0.0500),(24,'C',0.0500),(24,'D',0.0400),(24,'E',0.0600),(24,'F',0.0400);
/*!40000 ALTER TABLE `prevalence_rates` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `preventions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `preventions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `disease_id` int DEFAULT NULL,
  `content` varchar(200) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `disease_id` (`disease_id`),
  CONSTRAINT `preventions_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=107 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `preventions` WRITE;
/*!40000 ALTER TABLE `preventions` DISABLE KEYS */;
INSERT INTO `preventions` VALUES (1,1,'控制血压血脂'),(2,1,'完全戒烟'),(3,1,'每周150分钟有氧运动'),(4,1,'低盐低脂饮食'),(5,1,'定期心电图检查'),(6,1,'保持BMI<25'),(7,2,'接种肺炎疫苗'),(8,2,'接种流感疫苗'),(9,2,'勤洗手'),(10,2,'室内通风'),(11,2,'增强免疫力'),(12,3,'控制体重BMI<24'),(13,3,'每日运动30分钟'),(14,3,'低GI饮食'),(15,3,'监测血糖'),(16,3,'限制精制碳水'),(17,3,'充足睡眠'),(18,4,'严格控制血压'),(19,4,'房颤抗凝治疗'),(20,4,'低盐低脂饮食'),(21,4,'牢记FAST原则'),(22,4,'每年颈动脉超声'),(23,5,'每天盐<6克'),(24,5,'每周150分钟有氧'),(25,5,'管理压力'),(26,5,'限制饮酒'),(27,5,'家庭血压监测'),(28,6,'老人防跌倒'),(29,6,'补钙+维D'),(30,6,'运动前热身'),(31,6,'穿戴护具'),(32,6,'骨密度检查'),(33,7,'控制血压<130/80'),(34,7,'避免肾毒性药物'),(35,7,'每日饮水>1500ml'),(36,7,'低蛋白饮食'),(37,7,'定期查肾功能'),(38,8,'根除Hp四联疗法'),(39,8,'避免长期用NSAIDs'),(40,8,'三餐规律'),(41,8,'限制辛辣食物'),(42,8,'管理压力'),(43,9,'识别过敏原'),(44,9,'规律吸入控制药'),(45,9,'随身带沙丁胺醇'),(46,9,'保持环境清洁'),(47,9,'寒冷天戴口罩'),(48,9,'制定应急计划'),(49,10,'保持大便通畅'),(50,10,'防治肠道感染'),(51,10,'腹痛持续及时就医'),(52,11,'规律吃早餐'),(53,11,'低脂低胆固醇饮食'),(54,11,'控制体重多运动'),(55,11,'定期超声查胆结石'),(56,12,'每天饮水1500ml以上'),(57,12,'勤排尿不憋尿'),(58,12,'注意会阴部清洁'),(59,12,'性生活后及时排尿'),(60,13,'每天饮水2000ml以上'),(61,13,'限制高草酸食物（菠菜/浓茶）'),(62,13,'适量补钙勿过量'),(63,13,'结石病史者定期复查'),(64,14,'勤洗手，食物煮熟煮透'),(65,14,'生熟食品分开处理'),(66,14,'不吃变质剩饭菜'),(67,15,'控制三高（血压/血糖/血脂）'),(68,15,'戒烟限酒'),(69,15,'避免过劳与情绪激动'),(70,15,'随身携带硝酸甘油'),(71,16,'戒烟并远离二手烟'),(72,16,'感冒及时治疗'),(73,16,'寒冷季节注意保暖'),(74,16,'室内保持通风换气'),(75,17,'每年接种流感疫苗'),(76,17,'勤洗手、戴口罩'),(77,17,'流行期少去人群密集场所'),(78,17,'咳嗽打喷嚏掩口鼻'),(79,18,'新生儿接种卡介苗'),(80,18,'咳嗽掩口鼻、不随地吐痰'),(81,18,'全程规范用药防耐药'),(82,18,'密切接触者及时筛查'),(83,19,'多吃红肉、动物肝脏等富铁食物'),(84,19,'餐后1小时再饮浓茶咖啡'),(85,19,'月经过多及时就诊'),(86,19,'定期体检查血常规'),(87,20,'限制高嘌呤饮食（海鲜/内脏）'),(88,20,'戒酒（尤其啤酒）'),(89,20,'每天饮水2000ml以上'),(90,20,'控制体重、适度运动'),(91,21,'远离已知过敏原'),(92,21,'慎用易致敏药物'),(93,21,'作息规律、减少精神应激'),(94,21,'发作时避免搔抓和热水烫洗'),(95,22,'预防感冒，及时治鼻炎'),(96,22,'婴儿喂奶避免平躺'),(97,22,'不随意掏挖耳朵'),(98,22,'游泳后排出耳内积水'),(99,23,'勤洗手、勿用手揉眼'),(100,23,'毛巾脸盆专人专用'),(101,23,'隐形眼镜规范护理'),(102,23,'流行期避免去泳池游泳'),(103,24,'规律作息、保证睡眠'),(104,24,'少饮酒、少喝咖啡'),(105,24,'记录头痛日记找诱因'),(106,24,'适度运动、放松心情');
/*!40000 ALTER TABLE `preventions` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `symptoms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `symptoms` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(30) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=66 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `symptoms` WRITE;
/*!40000 ALTER TABLE `symptoms` DISABLE KEYS */;
INSERT INTO `symptoms` VALUES (29,'上腹痛'),(12,'乏力'),(11,'体重下降'),(13,'偏瘫'),(52,'关节痛'),(53,'关节红肿'),(3,'冷汗'),(23,'功能障碍'),(30,'反酸'),(5,'发热'),(39,'右上腹痛'),(37,'右下腹痛'),(59,'听力下降'),(38,'呕吐'),(2,'呼吸困难'),(49,'咯血'),(6,'咳嗽'),(7,'咳痰'),(48,'咽痛'),(33,'喘息'),(31,'嗳气'),(10,'多尿'),(9,'多饮'),(36,'夜间发作'),(14,'失语'),(18,'头晕'),(15,'头痛'),(26,'少尿'),(42,'尿急'),(43,'尿痛'),(41,'尿频'),(19,'心悸'),(4,'恶心'),(16,'昏迷'),(25,'水肿'),(54,'活动受限'),(63,'流泪'),(65,'畏光'),(24,'畸形'),(21,'疼痛'),(56,'瘙痒'),(55,'皮疹'),(50,'盗汗'),(64,'眼分泌物增多'),(62,'眼痛'),(61,'眼红'),(60,'耳流脓'),(58,'耳痛'),(47,'肌肉酸痛'),(22,'肿胀'),(1,'胸痛'),(34,'胸闷'),(44,'腰痛'),(46,'腹泻'),(45,'血尿'),(20,'视物模糊'),(51,'面色苍白'),(57,'风团'),(27,'食欲减退'),(40,'黄疸'),(32,'黑便');
/*!40000 ALTER TABLE `symptoms` ENABLE KEYS */;
UNLOCK TABLES;
DROP TABLE IF EXISTS `tests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tests` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(30) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=41 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

LOCK TABLES `tests` WRITE;
/*!40000 ALTER TABLE `tests` DISABLE KEYS */;
INSERT INTO `tests` VALUES (16,'X光'),(17,'三维CT'),(32,'便常规'),(3,'冠脉造影'),(27,'呼出气一氧化氮'),(10,'头部CT'),(31,'尿培养'),(20,'尿常规'),(23,'幽门螺杆菌检测'),(1,'心电图'),(11,'核磁共振'),(21,'活检'),(33,'流感抗原检测'),(6,'痰培养'),(34,'痰涂片'),(7,'空腹血糖'),(24,'粪便隐血'),(8,'糖化血红蛋白'),(9,'糖耐量试验'),(35,'结核菌素试验'),(38,'耳镜检查'),(2,'肌钙蛋白'),(30,'肝功能'),(25,'肺功能检查'),(15,'肾功能'),(22,'胃镜'),(4,'胸部CT'),(29,'腹部CT'),(28,'腹部超声'),(13,'血压监测'),(37,'血尿酸'),(5,'血常规'),(39,'裂隙灯检查'),(40,'视力检查'),(26,'过敏原检测'),(36,'铁代谢检查'),(12,'颈动脉超声');
/*!40000 ALTER TABLE `tests` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

