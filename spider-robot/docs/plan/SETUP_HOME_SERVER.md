# سيرفر البيت: شو بتعمل بإيدك

هالملف إلك إنت. كل الأوامر بتنكتب **على سيرفر البيت** (Ubuntu)، مش على الماك.
بعد ما تخلص هالخطوات، الـ agent بيدخل من الماك وبينزّل الباقي لحاله.

---

## 1. Tailscale (مشان الماك والروبوت يوصلوا للسيرفر من أي مكان)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

بيطلعلك رابط. افتحه وسجّل دخول **بنفس الحساب اللي على الماك والروبوت**.

## 2. SSH (مشان الـ agent يدخل)

```bash
sudo apt-get update
sudo apt-get install -y openssh-server
sudo systemctl enable --now ssh
```

## 3. اسمح لمفتاح الماك يدخل

انسخ هالأوامر متل ما هي. السطر الطويل هو المفتاح **العام** تبع الماك، ومش سري.

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP1vqd6a3j/VywVaLPKtvmqE5AUddppPAvIQ+EyBP6kN mac-claude' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

## 4. sudo بدون كلمة سر (متل الروبوت)

بدونها الـ agent بيعلق عند كل أمر فيه `sudo`. بدّل `kawas` باسم المستخدم تبعك إذا مختلف:

```bash
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/90-$USER-agent
sudo chmod 440 /etc/sudoers.d/90-$USER-agent
```

بعد ما ننقل لوي ونخلص التنزيل، فيك تشيلها بـ `sudo rm /etc/sudoers.d/90-$USER-agent`.

## 5. ابعت للـ agent هالنتيجة

```bash
echo "user: $USER"; tailscale ip -4; hostnamectl --static
nproc; free -h | head -2; df -h / | tail -1; lsb_release -ds
```

انسخ اللي طلع وابعته بالشات.

---

## شو بيعمل الـ agent بعدها (إنت ما بتعمل شي)

1. بيتأكد إنو بيقدر يدخل، وبيقيس الرام والقرص.
2. بيجيب كود الروبوت، وبيشغّل `infra/server/setup_server.sh`: بيبني llama-server ويحضّر الـ brain.
3. **بينقل لوي من AWS:** الكود والذاكرة كلها (تلغرام وواتساب والقروبات). سيرفر AWS بيضل موقّف ومش ممسوح لحتى تقول "تمام".
4. **المسابقة:** 30 جملة بلهجتك على كل موديل مرشّح (Qwen3.5 و Gemma 4 و ALLaM و Falcon-Arabic)، وبيقيس السرعة. إنت بتختار الأحلى.
5. بيربط لوي بالروبوت.

**لازم:** السيرفر يضل شغّال وموصول بالنت وقت الشغل.
