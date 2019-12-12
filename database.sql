create table activity_log
(
  uid  bigint       not null,
  game varchar(128) not null,
  time bigint default 0,
  constraint idx_27130_primary
    primary key (uid, game)
);

create table attachments
(
  channel    bigint not null,
  attachment text   not null,
  constraint idx_27134_primary
    primary key (channel)
);

create table automute_blacklist
(
  channel bigint not null,
  guild   bigint not null,
  constraint idx_27140_primary
    primary key (channel)
);

create index idx_27140_server_id
  on automute_blacklist (guild);

create table banned_users
(
  uid    bigint not null,
  reason text   not null,
  constraint idx_27146_primary
    primary key (uid)
);

create table bot_staff
(
  uid        bigint   not null,
  auth_level smallint not null,
  constraint idx_27152_primary
    primary key (uid)
);

create table changelog
(
  id      serial                              not null,
  changes text,
  time    timestamp default CURRENT_TIMESTAMP not null,
  constraint idx_27157_primary
    primary key (id)
);

create table command_blacklist
(
  id      bigserial not null,
  command text,
  type    smallint  not null,
  uid     bigint,
  role    bigint,
  channel bigint,
  guild   bigint,
  constraint idx_27170_primary
    primary key (id)
);

create index idx_27170_role
  on command_blacklist (role);

create index idx_27170_channel
  on command_blacklist (channel);

create index idx_27170_user
  on command_blacklist (uid);

create index idx_27170_server
  on command_blacklist (guild);

create table command_stats
(
  parent varchar(40) not null,
  cmd    varchar(200) default '0'::character varying,
  uses   bigint       default 0
);

create index idx_27177_uses
  on command_stats (uses);

create unique index idx_27177_parent
  on command_stats (parent, cmd);

create table emotes
(
  name  text        not null,
  emote varchar(20) not null,
  guild bigint,
  constraint idx_27182_primary
    primary key (emote)
);

create index idx_27182_server_id
  on emotes (guild);

create table giveaways
(
  guild      bigint   not null,
  title      text     not null,
  message    bigint   not null,
  channel    bigint   not null,
  winners    smallint not null,
  expires_in timestamp,
  constraint idx_27188_primary
    primary key (message)
);

create index idx_27188_server_id
  on giveaways (guild);

create table guilds
(
  guild             bigint not null,
  mute_role         bigint,
  modlog            bigint,

  on_delete_channel bigint,
  on_edit_channel   bigint,

  keeproles         boolean  default false,

  on_join_channel   bigint,
  on_leave_channel  bigint,
  on_join_message   text,
  on_leave_message  text,

  color_on_join     boolean  default false,

  on_edit_message   text,
  on_delete_message text,

  automute          boolean  default false,
  automute_limit    smallint default 10,
  automute_time     interval,

  on_delete_embed   boolean  default false,
  on_edit_embed     boolean  default false,

  dailygachi        bigint,

  last_banner TEXT DEFAULT NULL,
  constraint idx_27194_primary
    primary key (guild)
);

create table guild_blacklist
(
  guild  bigint not null,
  reason text   not null,
  constraint idx_27206_primary
    primary key (guild)
);

create table join_leave
(
  uid   bigint                              not null,
  at    timestamp default CURRENT_TIMESTAMP not null,
  guild bigint                              not null,
  value smallint                            not null,
  constraint idx_27212_primary
    primary key (uid, guild)
);

create table last_seen_users
(
  uid       bigint                              not null,
  username  varchar(40)                         not null,
  guild     bigint    default 0                 not null,
  last_seen timestamp default CURRENT_TIMESTAMP not null,
  constraint idx_27216_primary
    primary key (uid, guild)
);

create index idx_27216_username
  on last_seen_users (username);

create table mention_stats
(
  guild     bigint       not null,
  role      bigint       not null,
  role_name varchar(100) not null,
  amount    bigint default 1,
  constraint idx_27221_primary
    primary key (guild, role)
);

create table messages
(
  guild      bigint,
  channel    bigint,
  user_id    bigint,
  message_id bigint    default 0                 not null,
  constraint idx_27225_primary
    primary key (message_id)
);

create index idx_27225_user_id
  on messages (user_id);

create index idx_27225_channel_id
  on messages (channel);

create index idx_27225_server_id
  on messages (guild);

create index idx_27225_time
  on messages (time);

create table mute_roll_stats
(
  guild          bigint not null,
  uid            bigint not null,
  wins           integer  default 0,
  games          integer  default 1,
  current_streak smallint default 0,
  biggest_streak smallint default 0,
  constraint idx_27230_primary
    primary key (guild, uid)
);

create index idx_27230_wins
  on mute_roll_stats (wins);

create index idx_27230_games
  on mute_roll_stats (games);

create table nn_text
(
  message text not null
);

create table pokespawns
(
  guild bigint      not null,
  name  varchar(20) not null,
  count integer default 1,
  constraint idx_27243_primary
    primary key (guild, name)
);

create table polls
(
  guild          bigint not null,
  title          text   not null,
  strict         boolean default false,
  message        bigint not null,
  channel        bigint not null,
  expires_in     timestamp,
  ignore_on_dupe boolean default false,
  multiple_votes boolean default false,
  max_winners    integer default 1,
  giveaway       boolean default false,
  constraint idx_27250_primary
    primary key (message)
);

create table pollemotes
(
  poll_id  bigint      not null,
  emote_id varchar(20) not null,
  constraint idx_27247_primary
    primary key (poll_id, emote_id),
  constraint pollemotes_ibfk_1
    foreign key (poll_id) references polls
      on update cascade on delete cascade
);

create index idx_27247_emote_id
  on pollemotes (emote_id);

create index idx_27250_server_id
  on polls (guild);

create table prefixes
(
  prefix varchar(30) default '!'::character varying not null,
  guild  bigint                                     not null,
  constraint idx_27261_primary
    primary key (prefix, guild)
);

create table roles
(
  id    bigint not null,
  guild bigint not null,
  constraint idx_27265_primary
    primary key (id)
);

create table automute_whitelist
(
  role  bigint not null,
  guild bigint not null,
  constraint idx_27143_primary
    primary key (role),
  constraint automute_whitelist_ibfk_1
    foreign key (role) references roles
      on update restrict on delete cascade
);

create index idx_27143_server
  on automute_whitelist (guild);

create table colors
(
  id    bigint           not null,
  name  varchar(127)     not null,
  value integer          not null,
  lab_l double precision not null,
  lab_a double precision not null,
  lab_b double precision not null,
  constraint idx_27165_primary
    primary key (id),
  constraint colors_ibfk_1
    foreign key (id) references roles
      on update restrict on delete cascade
);

create index idx_27165_value
  on colors (value);

create index idx_27265_server
  on roles (guild);

create table role_granting
(
  user_role bigint not null,
  role      bigint not null,
  guild     bigint not null,
  uid       bigint not null,
  constraint idx_27268_primary
    primary key (user_role, role, uid),
  constraint role_granting_ibfk_2
    foreign key (role) references roles
      on update restrict on delete cascade
);

create index idx_27268_server_id
  on role_granting (guild);

create index idx_27268_role_id
  on role_granting (role);

create table temproles
(
  role       bigint                              not null,
  uid        bigint                              not null,
  guild      bigint                              not null,
  expires_at timestamp default CURRENT_TIMESTAMP not null,
  constraint idx_27271_primary
    primary key (role, uid)
);

create table timeouts
(
  guild      bigint    not null,
  uid        bigint    not null,
  expires_on timestamp not null,
  constraint idx_27274_primary
    primary key (uid, guild)
);

create table timeout_logs
(
  guild        bigint                              not null,
  uid          bigint                              not null,
  author       bigint                              not null,
  embed        text,
  reason       text                                not null,
  message      bigint,
  id           bigserial                           not null,
  time         timestamp default CURRENT_TIMESTAMP not null,
  duration     integer,
  show_in_logs boolean   default true,
  constraint idx_27279_primary
    primary key (id)
);

create index idx_27279_author
  on timeout_logs (author);

create index idx_27279_guild
  on timeout_logs (guild);

create index idx_27279_show_in_logs
  on timeout_logs (show_in_logs);

create index idx_27279_user
  on timeout_logs (uid);

create table timeout_logs_old
(
  guild  bigint not null,
  "user" bigint not null,
  time   bigint not null,
  reason text   not null
);

create index idx_27288_user
  on timeout_logs_old ("user");

create index idx_27288_guild
  on timeout_logs_old (guild);

create table todo
(
  time         timestamp default CURRENT_TIMESTAMP not null,
  completed_at timestamp,
  completed    boolean   default false,
  todo         text,
  priority     smallint  default 0                 not null,
  id           serial                              not null,
  constraint idx_27296_primary
    primary key (id)
);

create table userroles
(
  uid  bigint not null,
  role bigint not null,
  constraint idx_27306_primary
    primary key (uid, role),
  constraint userroles_ibfk_1
    foreign key (role) references roles
      on update restrict on delete cascade
);

create index idx_27306_role_id
  on userroles (role);

create table users
(
  id bigint not null,
  timezone text DEFAULT NULL,
  constraint idx_27309_primary
    primary key (id)
);
