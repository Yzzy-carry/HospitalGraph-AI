-- 联邦医院知识图谱AI · 数据库表结构（仅结构，无数据）
-- 生成时间: 见 README
CREATE DATABASE IF NOT EXISTS `hospital_graph` DEFAULT CHARSET utf8;
USE `hospital_graph`;

CREATE TABLE `disease_drugs` (
  `disease_id` int NOT NULL,
  `drug_id` int NOT NULL,
  PRIMARY KEY (`disease_id`,`drug_id`),
  KEY `drug_id` (`drug_id`),
  CONSTRAINT `disease_drugs_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`),
  CONSTRAINT `disease_drugs_ibfk_2` FOREIGN KEY (`drug_id`) REFERENCES `drugs` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `disease_symptoms` (
  `disease_id` int NOT NULL,
  `symptom_id` int NOT NULL,
  PRIMARY KEY (`disease_id`,`symptom_id`),
  KEY `symptom_id` (`symptom_id`),
  CONSTRAINT `disease_symptoms_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`),
  CONSTRAINT `disease_symptoms_ibfk_2` FOREIGN KEY (`symptom_id`) REFERENCES `symptoms` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `disease_tests` (
  `disease_id` int NOT NULL,
  `test_id` int NOT NULL,
  PRIMARY KEY (`disease_id`,`test_id`),
  KEY `test_id` (`test_id`),
  CONSTRAINT `disease_tests_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`),
  CONSTRAINT `disease_tests_ibfk_2` FOREIGN KEY (`test_id`) REFERENCES `tests` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
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
CREATE TABLE `drugs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(30) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=55 DEFAULT CHARSET=utf8mb3;
CREATE TABLE `hospitals` (
  `id` char(1) NOT NULL,
  `name` varchar(50) NOT NULL,
  `color` varchar(10) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `prevalence_rates` (
  `disease_id` int NOT NULL,
  `hospital_id` char(1) NOT NULL,
  `rate` decimal(5,4) DEFAULT NULL,
  PRIMARY KEY (`disease_id`,`hospital_id`),
  KEY `hospital_id` (`hospital_id`),
  CONSTRAINT `prevalence_rates_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`),
  CONSTRAINT `prevalence_rates_ibfk_2` FOREIGN KEY (`hospital_id`) REFERENCES `hospitals` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
CREATE TABLE `preventions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `disease_id` int DEFAULT NULL,
  `content` varchar(200) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `disease_id` (`disease_id`),
  CONSTRAINT `preventions_ibfk_1` FOREIGN KEY (`disease_id`) REFERENCES `diseases` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=107 DEFAULT CHARSET=utf8mb3;
CREATE TABLE `symptoms` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(30) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=66 DEFAULT CHARSET=utf8mb3;
CREATE TABLE `tests` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(30) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=41 DEFAULT CHARSET=utf8mb3;
