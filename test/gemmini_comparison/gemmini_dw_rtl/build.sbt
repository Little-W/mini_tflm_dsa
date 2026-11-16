ThisBuild / scalaVersion := "2.12.15"
ThisBuild / organization := "comparison"
ThisBuild / version := "0.1.0"
ThisBuild / scalacOptions ++= Seq("-deprecation", "-unchecked", "-Xsource:2.11", "-language:reflectiveCalls")

val chipyardRoot = file(sys.env("CHIPYARD_SOURCE"))
val gemminiRoot = file(sys.env("GEMMINI_SOURCE"))
val rocketRoot = chipyardRoot / "generators/rocket-chip"
val common = Seq(
  addCompilerPlugin("org.scalamacros" % "paradise" % "2.1.1" cross CrossVersion.full),
  addCompilerPlugin("edu.berkeley.cs" % "chisel3-plugin" % "3.5.2" cross CrossVersion.full),
  libraryDependencies ++= Seq(
    "edu.berkeley.cs" %% "chisel3" % "3.5.2",
    "org.scala-lang" % "scala-reflect" % scalaVersion.value,
    "org.json4s" %% "json4s-jackson" % "3.6.1",
    "org.apache.commons" % "commons-lang3" % "3.12.0",
    "org.apache.commons" % "commons-text" % "1.9"))

def sourceProject(name: String, path: File, resources: Option[File] = None) =
  Project(name, file("projects/" + name)).settings(common).settings(
    Compile / unmanagedSourceDirectories := Seq(path),
    Compile / unmanagedResourceDirectories := resources.toSeq)

lazy val cde = sourceProject("cde", rocketRoot / "api-config-chipsalliance/design/craft/src")
lazy val hardfloat = sourceProject("hardfloat", rocketRoot / "hardfloat/src/main/scala")
lazy val macros = sourceProject("macros", rocketRoot / "macros/src/main/scala")
lazy val rocket = sourceProject("rocket", rocketRoot / "src/main/scala", Some(rocketRoot / "src/main/resources")).dependsOn(cde, hardfloat, macros)
lazy val targetutils = sourceProject("targetutils", chipyardRoot / "sims/firesim/sim/midas/targetutils/src/main/scala")
lazy val testchip = (project in file("projects/testchip")).settings(common).settings(
  Compile / unmanagedSources := Seq(chipyardRoot / "generators/testchipip/src/main/scala/Util.scala")).dependsOn(rocket)
lazy val gemmini = sourceProject("gemmini", gemminiRoot / "src/main/scala",
  Some(gemminiRoot / "src/main/resources")).settings(
    Compile / unmanagedSources := (gemminiRoot / "src/main/scala" ** "*.scala").get.map { source =>
      if (source == gemminiRoot / "src/main/scala/gemmini/DMA.scala")
        file(sys.env("GEMMINI_DMA_SOURCE")) else source
    }).dependsOn(rocket, testchip, targetutils)
lazy val compare = (project in file(".")).settings(common).dependsOn(gemmini)
