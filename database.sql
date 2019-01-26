SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET time_zone = "+00:00";


CREATE TABLE `guilds` (
    `guild` BIGINT NOT NULL,
    `mute_role` BIGINT DEFAULT NULL,
    `modlog` BIGINT DEFAULT NULL,
    `keeproles` BOOL DEFAULT false,

    `on_join_channel` BIGINT DEFAULT NULL,
    `on_leave_channel` BIGINT DEFAULT NULL,
    `on_join_message` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `on_leave_message` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,

    `color_on_join` BOOL DEFAULT false,

    `on_delete_channel` BIGINT DEFAULT NULL,
    `on_edit_channel` BIGINT DEFAULT NULL,
    `on_delete_embed` BOOL DEFAULT false,
    `on_edit_embed` BOOL DEFAULT false,
    `on_edit_message` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `on_delete_message` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    --`on_bulk_delete` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,

    `automute` BOOL DEFAULT false,
    `automute_limit` TINYINT DEFAULT 10,
    `automute_time` TIME DEFAULT NULL,

    `dailygachi` BIGINT DEFAULT NULL,

    PRIMARY KEY (`guild`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `automute_whitelist` (
    `role` BIGINT NOT NULL,
    `guild` BIGINT NOT NULL,
    PRIMARY KEY (`role`),
    KEY (`guild`),
    FOREIGN KEY (`role`) REFERENCES `roles` (`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE `prefixes` (
    `prefix` VARCHAR(30) COLLATE utf8mb4_unicode_ci DEFAULT "!" NOT NULL,
    `guild` BIGINT NOT NULL,
    PRIMARY KEY (`prefix`, `guild`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `colors` (
    `id` BIGINT NOT NULL,
    `name` VARCHAR(127) COLLATE utf8mb4_unicode_ci NOT NULL,
    `value` MEDIUMINT UNSIGNED NOT NULL,
    `lab_l` FLOAT NOT NULL,
    `lab_a` FLOAT NOT NULL,
    `lab_b` FLOAT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`id`) REFERENCES `roles` (`id`)
        ON DELETE CASCADE,
    KEY (`value`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `command_blacklist` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `command` TEXT DEFAULT NULL,
    `type` TINYINT NOT NULL,
    `user` BIGINT DEFAULT NULL,
    `role` BIGINT DEFAULT NULL,
    `channel` BIGINT DEFAULT NULL,
    `guild` BIGINT DEFAULT NULL,
    PRIMARY KEY (`id`),
    KEY (`user`),
    KEY (`role`),
    KEY (`guild`),
    KEY (`channel`)
) ENGINE=MyISAM;


CREATE TABLE `bot_staff` (
    `user` BIGINT NOT NULL,
    `auth_level` TINYINT NOT NULL,
    PRIMARY KEY `user_id` (`user`)
) ENGINE=MyISAM;


CREATE TABLE `banned_users` (
    `user` BIGINT NOT NULL,
    `reason` TEXT NOT NULL,
    PRIMARY KEY `user_id` (`user`)
) ENGINE=InnoDB;


CREATE TABLE `guild_blacklist` (
    `guild` BIGINT NOT NULL,
    `reason` TEXT NOT NULL,
    PRIMARY KEY (`guild`)
) ENGINE=InnoDB;

-- https://stackoverflow.com/a/8048494/6046713 restrict row count
CREATE TABLE `messages` (
    `shard` SMALLINT DEFAULT NULL,
    `guild` BIGINT DEFAULT NULL,
    `channel` BIGINT DEFAULT NULL,
    `user_id` BIGINT NOT NULL,
    `message_id` BIGINT NOT NULL,
    `time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `attachment` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    PRIMARY KEY (`message_id`),
    KEY (`guild`),
    KEY (`channel`),
    KEY (`user_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `polls` (
    `guild` BIGINT NOT NULL,
    `title` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    `strict` BOOL DEFAULT false,
    `message` BIGINT NOT NULL,
    `channel` BIGINT NOT NULL,
    `expires_in` datetime DEFAULT NULL,
    `ignore_on_dupe` BOOL DEFAULT false,
    `multiple_votes` BOOL DEFAULT false,
    `max_winners` SMALLINT UNSIGNED DEFAULT 1,
    PRIMARY KEY `message_id` (`message`),
    KEY (`guild`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `emotes` (
    `name` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    `emote` VARCHAR(20) COLLATE utf8mb4_unicode_ci NOT NULL,
    `guild` BIGINT DEFAULT NULL,
    PRIMARY KEY (`emote`),
    KEY (`guild`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `pollEmotes` (
    `poll_id` BIGINT NOT NULL,
    `emote_id` VARCHAR(20) COLLATE utf8mb4_unicode_ci NOT NULL,
    PRIMARY KEY (`poll_id`,`emote_id`),
    FOREIGN KEY (`poll_id`) REFERENCES `polls`(`message`)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`emote_id`) REFERENCES `emotes`(`emote`)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `giveaways` (
    `guild` BIGINT NOT NULL,
    `title` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    `message` BIGINT NOT NULL,
    `channel` BIGINT NOT NULL,
    `winners` SMALLINT NOT NULL,
    `expires_in` datetime DEFAULT NULL,
    PRIMARY KEY `message_id` (`message`),
    KEY (`guild`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `timeouts`(
    `guild` BIGINT NOT NULL,
    `user` BIGINT NOT NULL,
    `reason` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    `expires_on` datetime NOT NULL,
    PRIMARY KEY (`user`, `guild`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `timeout_logs` (
    `guild` BIGINT NOT NULL,
    `user` BIGINT NOT NULL,
    `author` BIGINT NOT NULL,
    `embed` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `reason` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    PRIMARY KEY (`guild`, `user`),
    KEY (`author`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `join_leave`(
    `user_id` BIGINT NOT NULL,
    `at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `guild` BIGINT NOT NULL,
    `value` TINYINT NOT NULL,
    PRIMARY KEY (`user`, `guild`)
) ENGINE=InnoDB;


CREATE TABLE `role_granting` (
    `user_role` BIGINT NOT NULL,
    `user` BIGINT NOT NULL,
    `role` BIGINT NOT NULL,
    `guild` BIGINT NOT NULL,
    PRIMARY KEY (`user_role`, `role`, `user`),
    KEY (`guild`),

    FOREIGN KEY (`user_role`) REFERENCES `roles`(`id`)
        ON DELETE CASCADE,
    FOREIGN KEY (`role`) REFERENCES `roles`(`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE `mention_stats`(
    `guild` BIGINT NOT NULL,
    `role` BIGINT NOT NULL,
    `role_name` VARCHAR(100) COLLATE utf8mb4_unicode_ci NOT NULL,
    `amount` INT DEFAULT 1,
    PRIMARY KEY (`guild`, `role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `users` (
    `id` BIGINT NOT NULL,
    -- `username` VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `roles` (
    `id` BIGINT NOT NULL,
    `guild` BIGINT NOT NULL,
    PRIMARY KEY (`id`),
    KEY (`guild`)
) ENGINE=InnoDB;


CREATE TABLE `userRoles` (
    `user` BIGINT NOT NULL,
    `role` BIGINT NOT NULL,
    PRIMARY KEY (`user`,`role`),
    FOREIGN KEY (`role`) REFERENCES `roles`(`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB;


CREATE TABLE `automute_blacklist` (
    `channel` BIGINT NOT NULL,
    `guild` BIGINT NOT NULL,
    PRIMARY KEY (`channel`),
    KEY (`guild`)
) ENGINE=InnoDB;


CREATE TABLE `nn_text` (
    `message` TEXT COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `last_seen_users` (
    `user` BIGINT NOT NULL,
    `username` VARCHAR(40) COLLATE utf8mb4_unicode_ci NOT NULL,
    `guild` BIGINT DEFAULT 0,
    `last_seen` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`user`, `guild`),
    KEY (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `activity_log` (
    `user` BIGINT NOT NULL,
    game VARCHAR(128) COLLATE utf8mb4_unicode_ci NOT NULL,
    time INT DEFAULT 0,
    PRIMARY KEY (`user`, `game`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `command_stats` (
    `parent` VARCHAR(40) COLLATE utf8_unicode_ci NOT NULL,
    `cmd` VARCHAR(200) COLLATE utf8_unicode_ci DEFAULT 0,
    `uses` BIGINT DEFAULT 0,
    UNIQUE KEY (`parent`, `cmd`),
    KEY (`uses`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `mute_roll_stats` (
    `guild` BIGINT NOT NULL,
    `user` BIGINT NOT NULL,
    `wins` TINYINT UNSIGNED DEFAULT 0,
    `games` TINYINT UNSIGNED DEFAULT 1,
    `current_streak` TINYINT UNSIGNED DEFAULT 0,
    `biggest_streak` TINYINT UNSIGNED DEFAULT 0,
    PRIMARY KEY (`guild`, `user`),
    KEY (`wins`),
    KEY (`games`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `pokespawns` (
    `guild` BIGINT NOT NULL,
    `name` VARCHAR(20) COLLATE utf8_unicode_ci NOT NULL,
    `count` MEDIUMINT UNSIGNED DEFAULT 1,
    PRIMARY KEY (`guild`, `name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `todo` (
    `time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `completed_at` TIMESTAMP NULL DEFAULT NULL,
    `completed` BOOL DEFAULT FALSE,
    `todo` TEXT COLLATE utf8mb4_unicode_ci,
    `priority` TINYINT UNSIGNED NOT NULL DEFAULT 0,
    `id` MEDIUMINT UNSIGNED NOT NULL AUTO_INCREMENT,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `temproles` (
    `role` BIGINT NOT NULL,
    `user` BIGINT NOT NULL,
    `guild` BIGINT NOT NULL,
    `expires_at` TIMESTAMP NOT NULL,

    PRIMARY KEY (`role`, `user`)
) ENGINE=InnoDB;


CREATE TABLE `changelog` (
    `id` SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `changes` TEXT COLLATE utf8mb4_unicode_ci,
    `time` TIMESTAMP DEFAULT UTC_TIMESTAMP,

    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
------------------------
-- UNDER CONSTRUCTION --
------------------------
