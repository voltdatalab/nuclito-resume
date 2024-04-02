import React from "react";
import "../App.css";
import Post from "./post";
import Slider from "react-slick";

const settings = {
  dots: true,
  infinite: false,
  speed: 500,
  slidesToShow: 1,
  slidesToScroll: 1,
};

const SlideShow = ({ posts, lang }) => (
  <div>
    <p className="tutorial">
      {lang === "pt_BR" ? "Arraste para o lado\t" : "Swipe left\t"}
      <i className="fa-regular fa-hand-point-right"></i>
    </p>
    <Slider {...settings}>
      {posts.map((post) => <Post data={post} lang={lang} />)}
    </Slider>
  </div>
);

export default SlideShow;
