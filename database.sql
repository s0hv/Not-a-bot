SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET time_zone = "+00:00";


CREATE TABLE `servers` (
    `server` BIGINT NOT NULL,
    `prefix` VARCHAR(255) DEFAULT "!",
    `mute_role` BIGINT DEFAULT NULL,
    `modlog` BIGINT DEFAULT NULL,
    `on_delete_channel` BIGINT DEFAULT NULL,
    `on_edit_channel` BIGINT DEFAULT NULL,
    `keeproles` BOOL DEFAULT false,

    `automute` BOOL DEFAULT false,
    `automute_limit` TINYINT DEFAULT 10,

    `on_join_channel` BIGINT DEFAULT NULL,
    `on_leave_channel` BIGINT DEFAULT NULL,
    `on_join_message` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `on_leave_message` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,

    `on_edit_message` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `on_delete_message` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    --`on_bulk_delete` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    `color_on_join` BOOL DEFAULT false,

    PRIMARY KEY (`server`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `automute_whitelist` (
    `role` BIGINT NOT NULL,
    `server` BIGINT NOT NULL,
    PRIMARY KEY (`role`),
    KEY (`server`),
    FOREIGN KEY (`role`) REFERENCES `roles` (`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE `prefixes` (
    `prefix` VARCHAR(30) COLLATE utf8mb4_unicode_ci DEFAULT "!" NOT NULL,
    `server` BIGINT NOT NULL,
    PRIMARY KEY (`prefix`, `server`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `serverColors` (
    `server_id` BIGINT NOT NULL,
    `color_id` BIGINT NOT NULL,
    PRIMARY KEY (`server_id`, `color_id`)
    FOREIGN KEY (`server_id`) REFERENCES `servers`(`server`)
        ON DELETE CASCADE,
    FOREIGN KEY (`color_id`) REFERENCES `colors`(`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB;


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
    `server` BIGINT DEFAULT NULL,
    PRIMARY KEY (`id`),
    KEY (`user`),
    KEY (`role`),
    KEY (`server`),
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
)

-- https://stackoverflow.com/a/8048494/6046713 restrict row count
CREATE TABLE `messages` (
    `shard` SMALLINT DEFAULT NULL,
    `server` BIGINT DEFAULT NULL,
    `channel` BIGINT DEFAULT NULL,
    `user` VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
    `user_id` BIGINT NOT NULL,
    `message` TEXT COLLATE utf8mb4_unicode_ci,
    `message_id` BIGINT NOT NULL,
    `time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `attachment` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
    PRIMARY KEY (`message_id`),
    KEY `server_id` (`server`),
    KEY `channel_id` (`channel`)
    KEY (`user_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `polls` (
    `server` BIGINT NOT NULL,
    `title` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    `strict` BOOL DEFAULT false,
    `message` BIGINT NOT NULL,
    `channel` BIGINT NOT NULL,
    `expires_in` datetime DEFAULT NULL,
    `ignore_on_dupe` BOOL DEFAULT false,
    `multiple_votes` BOOL DEFAULT false,
    PRIMARY KEY `message_id` (`message`),
    KEY `server_id` (`server`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `emotes` (
    `name` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    `emote` BIGINT NOT NULL,
    `server` BIGINT DEFAULT NULL,
    PRIMARY KEY (`emote`),
    KEY `server_id` (`server`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `pollEmotes` (
    `poll_id` BIGINT NOT NULL,
    `emote_id` BIGINT NOT NULL,
    PRIMARY KEY (`poll_id`,`emote_id`),
    FOREIGN KEY (`poll_id`) REFERENCES `polls`(`message`)
        ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`emote_id`) REFERENCES `emotes`(`emote`)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;


CREATE TABLE `giveaways` (
    `server` BIGINT NOT NULL,
    `title` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
    `message` BIGINT NOT NULL,
    `channel` BIGINT NOT NULL,
    `winners` SMALLINT NOT NULL,
    `expires_in` datetime DEFAULT NULL,
    PRIMARY KEY `message_id` (`message`),
    KEY `server_id` (`server`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `timeouts`(
    `server` BIGINT NOT NULL,
    `user` BIGINT NOT NULL,
    `expires_on` datetime NOT NULL,
    PRIMARY KEY (`user`, `server`)
) ENGINE=InnoDB;


CREATE TABLE `join_leave`(
    `user_id` BIGINT NOT NULL,
    `at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `server` BIGINT NOT NULL,
    `value` TINYINT NOT NULL,
    PRIMARY KEY (`user_id`, `server`)
) ENGINE=InnoDB;


CREATE TABLE `role_granting` (
    `user_role` BIGINT NOT NULL,
    `role_id` BIGINT NOT NULL,
    `server_id` BIGINT NOT NULL,
    PRIMARY KEY (`user_role`, `role_id`),
    KEY (`server_id`),

    FOREIGN KEY (`user_role`) REFERENCES `roles`(`id`)
        ON DELETE CASCADE,
    FOREIGN KEY (`role_id`) REFERENCES `roles`(`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE `mention_stats`(
    `server` BIGINT NOT NULL,
    `role` BIGINT NOT NULL,
    `role_name` VARCHAR(100) COLLATE utf8mb4_unicode_ci NOT NULL,
    `amount` INT DEFAULT 1,
    PRIMARY KEY (`server`, `role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `users` (
    `id` BIGINT NOT NULL,
    -- `username` VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `roles` (
    `id` BIGINT NOT NULL,
    `server` BIGINT NOT NULL,
    PRIMARY KEY (`id`),
    KEY (`server`)
) ENGINE=InnoDB;


CREATE TABLE `userRoles` (
    `user_id` BIGINT NOT NULL,
    `role_id` BIGINT NOT NULL,
    PRIMARY KEY (`user_id`,`role_id`),
    FOREIGN KEY (`role_id`) REFERENCES `roles`(`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB;


CREATE TABLE `automute_blacklist` (
    `channel_id` BIGINT NOT NULL,
    `server_id` BIGINT NOT NULL,
    PRIMARY KEY (`channel_id`),
    KEY (`server_id`)
) ENGINE=InnoDB;


CREATE TABLE `nn_text` (
    `message` TEXT COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE `last_seen_users` (
    `user_id` BIGINT NOT NULL,
    `username` VARCHAR(40) COLLATE utf8mb4_unicode_ci NOT NULL,
    `server_id` BIGINT DEFAULT 0,
    `last_seen` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`, `server_id`),
    KEY (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
------------------------
-- UNDER CONSTRUCTION --
------------------------
