angular.module('aiddataDET')
.controller('OptionsCtrl', function($scope, $rootScope, $log, queryFactory) {
  $scope.dataset = {};

  $scope.options = [
    {
      name: 'Extract Options',
      type: 'checkbox',
      loc: 'options.extract_types',
      pick: 'name',
      data: []
    },
    {
      name: 'Resources',
      type: 'checkbox',
      loc: 'resources',
      pick: ['name', 'path'],
      data: []
    },
    {
      name: 'Metadata',
      type: 'paragraph'
    }
  ];

  $scope.toggleOption = function (isChecked, val, option) {
    $log.debug(isChecked, val, option);

    return isChecked ? queryFactory.toggleOptionOn(option, val) :
      queryFactory.toggleOptionOff(option, val);
  };

  $scope.getTimeStamp = function (date, format) {
    var timeFormatter = d3.timeFormat('%b %d, %Y');
    var timeParser = d3.timeParse(format),
        formDate = timeFormatter(timeParser(date));
    return formDate;
  };

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;

    if (data.type === 'raster') {
      _.each($scope.options, resetOption);
    }
  });

  function resetOption (option) {
    if (option.type === 'checkbox') {
      option.data = _.chain($scope.dataset)
        .get(option.loc)
        .map(function(choice) {
          return _.isString(choice) ? { name: choice } : choice;
        })
        .value();
    } else {
      /* Format Metadata Here */
    }
  }

});
