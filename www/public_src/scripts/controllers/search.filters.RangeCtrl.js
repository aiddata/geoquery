angular.module('aiddataDET')
.controller('RangeCtrl', function($scope, $rootScope, $log, $timeout, queryFactory) {
  // $scope.filterData
  // $scope.filterOptions
  // $scope.activeFilters

  var min = _.min($scope.filterOptions),
      max = _.max($scope.filterOptions);
  $scope.showSlider = false;
  $scope.range = { min: min, max: max };

  $scope.sliderOptions = {};

  $scope.fields = [
    {
      text: 'min',
      validate: function (val) {
        // $scope.range.min = val < $scope.sliderOptions.floor || val > $scope.range.max ? $scope.sliderOptions.floor : val;
        $scope.updateRange();
      }
    },
    {
      text: 'max',
      validate: function (val) {
        // $scope.range.max = val < $scope.range.min || val > $scope.sliderOptions.ceil ? $scope.sliderOptions.ceil : val;
        $scope.updateRange();
      }
    }
  ];

  $scope.updateRange = function () {
    console.log('update range');
    if (
      $scope.range.min === $scope.sliderOptions.floor &&
      $scope.range.max === $scope.sliderOptions.ceil &&
      $scope.filterOptions.length > 1
    ) {
      queryFactory.resetFilterRange($scope.filterData.field);
    } else {
      queryFactory.updateFilterRange($scope.range.min, $scope.range.max, $scope.filterData.field);
    }
  };

  $rootScope.$on('filters:resetRange', function(event, data) {
    if (data.filterId === $scope.filterData.field) {
      $scope.range.min = $scope.sliderOptions.floor;
      $scope.range.max = $scope.sliderOptions.ceil;
    }
  });

  $scope.$watch('filterOptions', function(newValue, oldValue) {
    var updateMin = $scope.range.min === min || newValue.length <= 1,
        updateMax = $scope.range.max === max || newValue.length <= 1;

    min = newValue.length ? _.floor(_.min(newValue)) : 0;
    max = newValue.length ? _.ceil(_.max(newValue)) : 0;

    $scope.range.min = updateMin || $scope.range.min < min ? min : $scope.range.min;
    $scope.range.max = updateMax || $scope.range.max > max ? max : $scope.range.max;

    $timeout(function () {
      buildSlider();
      $scope.updateRange();
    }, 500);

  }, true);

  function buildSlider () {
    $scope.sliderOptions = {
      floor: _.floor(min),
      ceil: _.ceil(max),
      onEnd: function() { $scope.updateRange(); },
      enforceRange: true,
      translate: function(val) { return '$' + val; }
    };
  }

  buildSlider();
  $timeout(function () {
    $scope.showSlider = true;
  }, 500);

});
