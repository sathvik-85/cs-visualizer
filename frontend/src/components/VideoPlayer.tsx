interface Props {
  videoUrl: string;
  jobId: string;
}

export function VideoPlayer({ videoUrl, jobId }: Props) {
  return (
    <div className="video-player">
      <video
        key={videoUrl}
        controls
        autoPlay
        src={videoUrl}
        className="video-element"
      />
      <a
        href={videoUrl}
        download={`${jobId}.mp4`}
        className="download-btn"
      >
        Download MP4
      </a>
    </div>
  );
}
