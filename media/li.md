Containerized 𝐆𝐞𝐫𝐦𝐚𝐧𝐃𝐮𝐛𝐈 📦

Some of you might remember I released GermanDubI this week – a tool with a neat UI/UX to replace the English audio track of YouTube videos with a German one. Works quite well and has already served its purpose several times. The kids could watch some interesting historical videos.

So, a release does not mean my work stops. Software engineering as a craft means you maintain the product after its release. #SDLC – maybe some have heard about it ;)

Using products also reveals some sporadic issues (dubbing could lead, in 5% of the runs, to a 100% CPU spin for ffmpeg, because of some overlapping tracks) – all known ones are fixed now. I bumped all dependencies.
And I did one thing I forgot: I containerized the whole app. So the Docker image is now available on #ghcr.

    $ 𝐝𝐨𝐜𝐤𝐞𝐫 𝐩𝐮𝐥𝐥 𝐠𝐡𝐜𝐫.𝐢𝐨/𝐦𝐚𝐫𝐜𝐞𝐥𝐩𝐞𝐭𝐫𝐢𝐜𝐤/𝐠𝐞𝐫𝐦𝐚𝐧𝐝𝐮𝐛𝐢:𝐥𝐚𝐭𝐞𝐬𝐭

And after that, it is a one- or two-liner copy-pasted to get it running. For 𝐱𝟔𝟒 and 𝐀𝐑𝐌 platforms.

I've already seen 16 downloads (🥹), so definitely not "no one" is using it. On the other hand: 𝐈 𝐚𝐥𝐰𝐚𝐲𝐬 𝐰𝐨𝐧𝐝𝐞𝐫 𝐢𝐟 𝐢𝐭 𝐦𝐚𝐤𝐞𝐬 𝐬𝐞𝐧𝐬𝐞 𝐭𝐨 𝐠𝐨 𝐭𝐡𝐞 𝐥𝐚𝐬𝐭 𝐦𝐢𝐥𝐞 𝐚𝐧𝐝 𝐜𝐨𝐧𝐭𝐚𝐢𝐧𝐞𝐫𝐢𝐳𝐞 𝐚𝐩𝐩𝐬. What is your view?

ps. the release version 0.4.2 is just a random match, not forced
